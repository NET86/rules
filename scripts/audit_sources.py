#!/usr/bin/env python3
"""Read-only secondary radar: report uncovered narrow domains, never mutate production."""

from rules import ROOT, FORBIDDEN_CORE, Rule, json_text, read_json
from sync import fetch


def covered(candidate, existing):
    return any(
        candidate == rule or
        (rule.kind == "DOMAIN-SUFFIX" and candidate.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and rule.matches(candidate.value)) or
        (candidate.kind == "DOMAIN" and rule.kind == "DOMAIN-REGEX" and rule.matches(candidate.value))
        for rule in existing
    )


def analyze(source, content, existing):
    ignored = set(source.get("ignore_rules", []))
    wanted_sections = set(source.get("sections", []))
    seen_sections = set()
    active = []
    section = None
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("# >> "):
            section = line.removeprefix("# >> ").strip()
            if section in wanted_sections:
                seen_sections.add(section)
            continue
        if wanted_sections and section not in wanted_sections:
            continue
        if not line or line.startswith(("#", "//", ";", "[")) or "," not in line:
            continue
        active.append((section, line))
    if wanted_sections and seen_sections != wanted_sections:
        raise ValueError(f"Secondary radar sections changed: {sorted(wanted_sections - seen_sections)}")
    if not active:
        raise ValueError(f"Unexpected empty rule response: {source['id']}")
    gaps, excluded, already_covered = {}, 0, 0
    for section, line in sorted(set(active), key=lambda row: ((row[0] or ""), row[1])):
        if line in ignored:
            excluded += 1
            continue
        fields = line.split(",")
        if len(fields) < 2 or fields[0] not in {"DOMAIN", "DOMAIN-SUFFIX"}:
            excluded += 1
            continue
        candidate = Rule.from_text(fields[0] + "," + fields[1].lower())
        if covered(candidate, existing):
            already_covered += 1
        elif candidate.value in FORBIDDEN_CORE:
            excluded += 1
        else:
            gaps[candidate.text] = section
    pending = [
        {"source_id": source["id"], "source": source["url"], "section": gaps[rule], "rule": rule,
         "reason": "uncovered-secondary-domain",
         "action": "Radar only: require v2fly, official evidence or an explicit reviewed patch before production"}
        for rule in sorted(gaps)
    ]
    summary = {
        "active_line_count": len(set(active)), "covered_count": already_covered,
        "excluded_by_policy_count": excluded, "gap_count": len(pending), "role": source["role"],
        "sections": sorted(seen_sections),
    }
    return pending, summary


def main():
    config = read_json(ROOT / "sources/watch.json")
    manifest = read_json(ROOT / "rules/manifest.json")
    existing = {Rule.from_text(row["rule"]) for row in manifest["provenance"]}
    report = {
        "schema": 3, "review_required": [], "sources": {},
        "action": "Read-only radar. Covered/ignored changes are silent; uncovered domains never change production automatically.",
    }
    for source in config["sources"]:
        try:
            content = fetch(source["url"]).decode("utf-8-sig")
            pending, summary = analyze(source, content, existing)
            report["review_required"].extend(pending)
            report["sources"][source["id"]] = summary
        except (OSError, ValueError) as exc:
            report["review_required"].append({
                "source_id": source["id"], "source": source["url"],
                "reason": "secondary-radar-unavailable", "error_type": type(exc).__name__,
            })
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    (work / "source-audit.json").write_text(json_text(report), encoding="utf-8", newline="\n")
    print(f"OK: checked {len(config['sources'])} read-only radar source(s); {len(report['review_required'])} exception(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
