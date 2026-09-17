"""Conservative unattended reconciliation; quarantine uncertainty, preserve availability."""
from __future__ import annotations

from datetime import date

from rules import FORBIDDEN_CORE, Rule, check_approvals


def key_of(row):
    return row["vendor"], row["tier"], Rule.from_text(row["rule"])


def row_of(key, sources):
    vendor, tier, rule = key
    return {"vendor": vendor, "tier": tier, "rule": rule.text, "sources": sorted(sources)}


def scope_problem(key, approvals, patches):
    vendor, tier, rule = key
    if rule.kind not in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-REGEX"}:
        return "unsupported-or-broad-matching"
    if tier == "core" and rule.value in FORBIDDEN_CORE:
        return "shared-platform-forbidden-in-core"
    if rule.kind == "DOMAIN-REGEX" and rule.value not in patches.get("surge_regex", {}):
        return "unreviewed-surge-regex-adapter"
    try:
        check_approvals({key: set()}, approvals)
    except ValueError:
        return "new-or-widened-scope"
    return None


def effective_entries(candidates, approvals, patches, state):
    """Offline compilation cannot promote quarantined entries or unapproved carryovers."""
    entries = {key: set(value) for key, value in candidates.items() if not scope_problem(key, approvals, patches)}
    for row in state.get("retained", []):
        key = key_of(row)
        if scope_problem(key, approvals, patches):
            raise ValueError(f"Retained rule no longer approved: {key}")
        entries.setdefault(key, set()).update(row["sources"])
    return entries


def reconcile(candidates, previous_manifest, approvals, patches, previous_state, policy,
              today=None, allow_removals=False, contracts=None,
              source_observation_healthy=True, unhealthy_vendors=()):
    """Reconcile only observed changes; retained/failing inputs never age deletions."""
    today = today or date.today()
    day = today.isoformat()
    contracts = contracts or {"vendors": {}}
    unhealthy_vendors = set(unhealthy_vendors)
    accepted = {key: set(value) for key, value in candidates.items() if not scope_problem(key, approvals, patches)}
    old_pending = {key_of(row): row for row in previous_state.get("pending", [])}
    pending = []
    for key, sources in sorted(candidates.items()):
        reason = scope_problem(key, approvals, patches)
        if reason:
            row = row_of(key, sources)
            row.update(reason=reason, first_seen=old_pending.get(key, {}).get("first_seen", day))
            pending.append(row)
    before = {key_of(row): row for row in previous_manifest.get("provenance", [])}
    old_retained = {key_of(row): row for row in previous_state.get("retained", [])}
    retained, removed = [], []
    missing = set(before) - set(accepted)
    available = set(accepted) | missing
    frozen_vendors = set()
    for key in sorted(missing):
        vendor, tier, rule = key
        if scope_problem(key, approvals, patches):
            # Explicit policy withdrawal is a local decision, not an upstream
            # disappearance, so retention must never resurrect it.
            available.discard(key)
            removed.append(dict(row_of(key, before[key]["sources"]), reason="approval-withdrawn"))
            continue
        if rule.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and any(
            v == vendor and t == tier and other.kind == "DOMAIN-SUFFIX" and other.matches(rule.value)
            for v, t, other in accepted
        ):
            available.discard(key)
            removed.append(dict(row_of(key, before[key]["sources"]), reason="covered-by-current-rule"))
            continue

        observation_healthy = source_observation_healthy and vendor not in unhealthy_vendors
        prior = old_retained.get(key, {})
        observations = set(prior.get("observation_days", []))
        first = prior.get("first_missing")
        if observation_healthy:
            observations.add(day)
            first = first or day
        else:
            frozen_vendors.add(vendor)
        observations = sorted(observations)
        age = (today - date.fromisoformat(first)).days if first else 0
        row = row_of(key, before[key]["sources"])
        row.update(observation_days=observations, protected=False)
        if first:
            row["first_missing"] = first

        remaining = {k for k in available if k != key and k[0] == vendor and k[1] == tier}
        critical_hosts = contracts.get("vendors", {}).get(vendor, {}).get("must_match", [])
        protected = not remaining or (tier == "core" and any(
            rule.matches(host) and not any(k[2].matches(host) for k in remaining)
            for host in critical_hosts
        ))
        row["protected"] = protected
        ready = (observation_healthy and first is not None
                 and age >= policy["removal_grace_days"]
                 and len(observations) >= policy["removal_min_observation_days"])
        # Maintainer override skips the time buffer, never source-health or
        # semantic-contract protection.
        if observation_healthy and (ready or allow_removals) and not protected:
            available.discard(key)
            removed.append(dict(row_of(key, row["sources"]), reason="confirmed-upstream-removal"))
        else:
            keep = policy["removal_min_observation_days"]
            row["observation_days"] = observations[:max(0, keep - 1)] + observations[max(max(0, keep - 1), len(observations) - 1):]
            retained.append(row)
    state = {"schema": 1, "pending": pending, "retained": retained}
    report = {
        "schema": 2,
        "review_required": pending + [dict(row, reason="protected-upstream-removal") for row in retained if row["protected"]],
        "quarantined_count": len(pending), "retained_count": len(retained),
        "automatically_removed": removed,
        "deletion_observation_frozen_vendors": sorted(frozen_vendors),
        "action": "Only healthy observations age deletions; uncertain changes are retained or quarantined while safe vendors continue."
    }
    return state, report
