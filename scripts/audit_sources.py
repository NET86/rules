#!/usr/bin/env python3
"""Read-only secondary radar: report uncovered narrow domains, never mutate production."""

import os
from pathlib import Path

from automation import scope_problem
from rules import ROOT, FORBIDDEN_CORE, Rule, json_text, load_source, read_json
from sync import fetch


SUMMARY_LIMIT = 10
REVIEW_REASON_LABELS = {
    "uncovered-secondary-domain": "Sukka 有、当前生产未覆盖；证据仅辅助复核，不会自动扩大生产边界",
    "secondary-radar-unavailable": "二级雷达来源不可用或结构变化",
}
SECTION_VENDOR = {
    "OpenAI / ChatGPT": "openai",
    "Perplexity": "perplexity",
    "Claude": "claude",
    "Google": "google-ai",
    "POE": "poe",
    "GitHub Copilot": "github-copilot",
    "Grok": "grok",
    "Cursor": "cursor",
}
BLOCK_REASON_LABELS = {
    "outside-explicit-product-select": "上游有该规则，但不在当前显式产品范围",
    "secondary-source-only": "目前仅 Sukka 证据命中，主上游尚未确认",
    "evidence-unavailable": "本地主上游证据暂不可用，需要复核",
    "new-or-widened-scope": "会扩大现有批准边界，需要人工确认",
    "shared-platform-forbidden-in-core": "属于共享基础设施，不能自动进入 core",
    "unreviewed-surge-regex-adapter": "新正则缺少已审核的 Surge 适配",
    "unsupported-or-broad-matching": "匹配类型不支持自动进入生产",
    "radar-read-only": "已落在现有批准边界；Sukka 雷达仍只读，等待主同步收敛",
    "unmapped-sukka-section": "Sukka section 尚未映射到本地厂商",
}


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


def rule_relation(candidate, evidence):
    """Describe whether one evidence rule supports the same candidate scope."""
    if candidate == evidence:
        return "exact"
    if evidence.kind == "DOMAIN-SUFFIX" and candidate.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and evidence.matches(candidate.value):
        return "evidence-covers-candidate"
    if candidate.value == evidence.value:
        return "same-domain-different-scope"
    if candidate.kind == "DOMAIN-SUFFIX" and evidence.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and candidate.matches(evidence.value):
        return "candidate-wider-than-evidence"
    return None


def vendor_spec(catalog, vendor):
    return next((row for row in catalog["vendors"] if row["id"] == vendor), None)


def impact_outputs(catalog, vendor):
    if vendor is None:
        return []
    return [vendor] + [
        name for name, spec in catalog.get("profiles", {}).items()
        if vendor in spec.get("members", [])
    ]


def v2fly_evidence(candidate, vendor, catalog, data):
    spec = vendor_spec(catalog, vendor)
    if spec is None:
        return {"status": "unavailable", "present": False, "level": "unknown", "matches": [], "error_type": "UnknownVendor"}
    entrypoints = sorted(set(spec.get("sources", [])) | set(spec.get("select", {})))
    matches = []
    try:
        for entrypoint in entrypoints:
            for rule, _attrs, origin in load_source(data, entrypoint):
                relation = rule_relation(candidate, rule)
                if relation:
                    matches.append({"entrypoint": entrypoint, "source": origin, "rule": rule.text, "relation": relation})
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "present": False, "level": "unknown", "matches": [], "error_type": type(exc).__name__}
    unique = {json_text(row).strip(): row for row in matches}
    matches = [unique[key] for key in sorted(unique)]
    strong = {"exact", "evidence-covers-candidate"}
    level = "confirmed" if any(row["relation"] in strong for row in matches) else ("related" if matches else "none")
    return {"status": "available", "present": bool(matches), "level": level, "matches": matches}


def official_evidence(candidate, vendor, state):
    matches = []
    for source_id, doc in state.get("documents", {}).items():
        if doc.get("vendor") != vendor:
            continue
        for text in doc.get("rules", []):
            rule = Rule.from_text(text)
            relation = rule_relation(candidate, rule)
            if relation:
                matches.append({
                    "source_id": source_id, "source": doc.get("url"),
                    "rule": rule.text, "relation": relation,
                })
    strong = {"exact", "evidence-covers-candidate"}
    level = "confirmed" if any(row["relation"] in strong for row in matches) else ("related" if matches else "none")
    return {"level": level, "matches": matches}


def product_scope(candidate, vendor, catalog, v2fly):
    spec = vendor_spec(catalog, vendor)
    if spec is None:
        return {"status": "unmapped", "basis": None}
    if spec.get("select"):
        selected = {value for values in spec["select"].values() for value in values}
        if candidate.value in selected:
            return {"status": "in-scope", "basis": "explicit-select"}
        if v2fly.get("present"):
            return {"status": "outside-explicit-select", "basis": "upstream-category-only"}
        return {"status": "unconfirmed", "basis": "explicit-select"}
    if spec.get("sources") and v2fly.get("present"):
        return {"status": "in-scope", "basis": "vendor-dedicated-v2fly-source"}
    return {"status": "unconfirmed", "basis": "vendor-section"}


def enrich_pending(pending, catalog, approvals, patches, official_state, data):
    """Add read-only evidence; never changes which Sukka findings require review."""
    enriched = []
    for original in pending:
        row = dict(original)
        candidate = Rule.from_text(row["rule"])
        vendor = SECTION_VENDOR.get(row.get("section"))
        row["vendor"] = vendor
        row["impact"] = impact_outputs(catalog, vendor)
        if vendor is None:
            row["evidence"] = {
                "v2fly": {"status": "unavailable", "present": False, "level": "unknown", "matches": []},
                "official": {"level": "none", "matches": []},
                "product_scope": {"status": "unmapped", "basis": None},
            }
            row["block_reason"] = "unmapped-sukka-section"
        else:
            upstream = v2fly_evidence(candidate, vendor, catalog, data)
            scope = product_scope(candidate, vendor, catalog, upstream)
            official = official_evidence(candidate, vendor, official_state)
            row["evidence"] = {"v2fly": upstream, "official": official, "product_scope": scope}
            if upstream.get("status") != "available":
                block = "evidence-unavailable"
            elif not upstream.get("present"):
                block = "secondary-source-only"
            elif scope["status"] == "outside-explicit-select":
                block = "outside-explicit-product-select"
            else:
                block = scope_problem((vendor, "core", candidate), approvals, patches) or "radar-read-only"
            row["block_reason"] = block
        row["block_reason_label"] = BLOCK_REASON_LABELS.get(row["block_reason"], row["block_reason"])
        enriched.append(row)
    return enriched


def format_review_item(row):
    subject = row.get("section") or row.get("source_id") or "secondary-radar"
    parts = [f"`{subject}`"]
    if row.get("rule"):
        parts.append(f"`{row['rule']}`")
    reason = row.get("reason", "unknown")
    text = " · ".join(parts) + " — " + REVIEW_REASON_LABELS.get(reason, reason)
    if row.get("error_type"):
        text += f"（{row['error_type']}）"
    if row.get("vendor"):
        impact = " / ".join(row.get("impact", [])) or "-"
        text += f"\n  - 厂商：`{row['vendor']}` · 若批准影响：{impact}"
        evidence = row.get("evidence", {})
        v2fly = evidence.get("v2fly", {})
        if v2fly.get("status") == "unavailable":
            v2fly_text = f"不可用（{v2fly.get('error_type', 'unknown')}）"
        elif v2fly.get("present"):
            sources = sorted({item["entrypoint"] for item in v2fly.get("matches", [])})
            v2fly_text = f"✓ {v2fly.get('level', 'unknown')} · " + ", ".join(sources)
        else:
            v2fly_text = "未命中"
        official = evidence.get("official", {})
        official_ids = sorted({item["source_id"] for item in official.get("matches", [])})
        official_text = official.get("level", "none") + ((" · " + ", ".join(official_ids)) if official_ids else "")
        scope = evidence.get("product_scope", {}).get("status", "unknown")
        text += f"\n  - 证据：V2Fly {v2fly_text} · 官方 {official_text} · 产品范围 {scope}"
        text += f"\n  - 拦截：{row.get('block_reason_label', row.get('block_reason', 'unknown'))}"
    return text


def render_actions_summary(report, limit=SUMMARY_LIMIT):
    summaries = list(report.get("sources", {}).values())
    active = sum(row.get("active_line_count", 0) for row in summaries)
    covered_count = sum(row.get("covered_count", 0) for row in summaries)
    excluded = sum(row.get("excluded_by_policy_count", 0) for row in summaries)
    gaps = sum(row.get("gap_count", 0) for row in summaries)
    review_required = report.get("review_required", [])

    lines = [
        "## Sukka 二级雷达",
        "",
        "### 扫描结果",
        f"- 有效规则：**{active}**",
        f"- 已覆盖：**{covered_count}**",
        f"- 策略排除：**{excluded}**",
        f"- 待核验缺口：**{gaps}**",
        f"- 待审核 / 异常：**{len(review_required)}**",
    ]
    if review_required:
        lines.extend(["", f"### 待审核 / 异常明细（{len(review_required)}）"])
        for row in review_required[:limit]:
            lines.append("- " + format_review_item(row))
        extra = len(review_required) - limit
        if extra > 0:
            lines.append(f"- 另有 **{extra}** 条，详见 sources exception Issue / source-audit.json。")
    return "\n".join(lines) + "\n"


def append_actions_summary(report):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        text = render_actions_summary(report)
    except Exception as exc:
        text = (
            "## Sukka 二级雷达\n\n"
            f"- 摘要生成失败：`{type(exc).__name__}`\n"
        )
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main():
    config = read_json(ROOT / "sources/watch.json")
    manifest = read_json(ROOT / "rules/manifest.json")
    catalog = read_json(ROOT / "sources/catalog.json")
    approvals = read_json(ROOT / "sources/approvals.json")
    patches = read_json(ROOT / "sources/patches.json")
    official_state = read_json(ROOT / "sources/official-state.json")
    v2fly_data = ROOT / "sources/snapshot/v2fly"
    existing = {Rule.from_text(row["rule"]) for row in manifest["provenance"]}
    report = {
        "schema": 4, "review_required": [], "sources": {},
        "action": "Read-only radar. Covered/ignored changes are silent; uncovered domains never change production automatically.",
    }
    for source in config["sources"]:
        try:
            content = fetch(source["url"]).decode("utf-8-sig")
            pending, summary = analyze(source, content, existing)
            report["review_required"].extend(
                enrich_pending(pending, catalog, approvals, patches, official_state, v2fly_data)
            )
            report["sources"][source["id"]] = summary
        except (OSError, ValueError) as exc:
            report["review_required"].append({
                "source_id": source["id"], "source": source["url"],
                "reason": "secondary-radar-unavailable", "error_type": type(exc).__name__,
            })
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    (work / "source-audit.json").write_text(json_text(report), encoding="utf-8", newline="\n")
    append_actions_summary(report)
    print(f"OK: checked {len(config['sources'])} read-only radar source(s); {len(report['review_required'])} exception(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
