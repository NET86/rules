#!/usr/bin/env python3
"""Deterministic AI rule compiler. Standard library only; never executes upstream code."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Keep one Rule class when this module is both the CLI entry point and imported
# by the reconciliation module during compilation.
sys.modules.setdefault("rules", sys.modules[__name__])

ROOT = Path(__file__).resolve().parents[1]
# A changed upstream license is a review gate, not an ordinary data update.
REVIEWED_V2FLY_LICENSE = "b9d84a22870d3f21c91a4c6e410c9cc51d00902f5233ad0c84011479244bf7d2"
PROJECT_URL = "https://github.com/NET86/rules"
RAW_URL = "https://raw.githubusercontent.com/NET86/rules/stable"
BUNDLE_DESCRIPTIONS = {
    "ai-daily": "日常 AI 核心域名，含 OpenAI 官方语音 IP。",
    "ai-core": "更多海外 AI 核心域名，不含语音 IP 和共享依赖。",
    "ai-cn": "国内 AI 服务分类，出口策略自行选择。",
    "openai-voice-ip": "OpenAI 官方语音目的 IP；ai-daily 已包含，单厂商 openai 未包含。",
}
DOMAIN_RE = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
TYPES = {"full": "DOMAIN", "domain": "DOMAIN-SUFFIX", "regexp": "DOMAIN-REGEX", "keyword": "DOMAIN-KEYWORD"}
FORBIDDEN_CORE = {
    "com", "net", "ai", "cn", "google.com", "googleapis.com", "gstatic.com",
    "amazonaws.com", "azure.com", "azureedge.net", "azurefd.net", "windows.net",
    "cloudfront.net", "cloudflare.com", "cloudflare.net", "github.com", "githubusercontent.com",
    "auth0.com", "stripe.com", "sentry.io", "intercom.io", "intercomcdn.com", "livekit.cloud", "unpkg.com",
    "storage.googleapis.com", "blob.core.windows.net", "webpubsub.azure.com", "api.github.com",
    "datadoghq.com", "segment.io", "algolia.net", "byteoversea.com", "microsoft.com",
    "s3.amazonaws.com", "s3.amazonaws.com.cn", "azurewebsites.net", "cloudapp.net",
    "github.io", "workers.dev", "pages.dev", "vercel.app", "netlify.app", "onrender.com",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.cn", "net.cn", "org.cn",
    "com.au", "net.au", "org.au", "co.jp", "co.nz", "co.in", "com.br", "com.sg"
}


def forbidden_core(value):
    """Known shared/public boundaries, including regional S3; not a complete PSL."""
    return value in FORBIDDEN_CORE or re.fullmatch(
        r"s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com(?:\.cn)?", value
    ) is not None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, order=True)
class Rule:
    kind: str
    value: str

    @property
    def text(self) -> str:
        return f"{self.kind},{self.value}"

    @classmethod
    def from_text(cls, text: str):
        fields = text.split(",")
        if len(fields) != 2:
            raise ValueError(f"Invalid domain rule: {text}")
        rule = cls(*fields)
        rule.validate()
        return rule

    def validate(self):
        if self.kind not in {*TYPES.values(), "DOMAIN-WILDCARD", "IP-CIDR", "IP-CIDR6"}:
            raise ValueError(f"Unsupported type: {self.kind}")
        if any(c.isspace() for c in self.value) or any(c in self.value for c in ",#\r\n"):
            raise ValueError(f"Unsafe value: {self.text}")
        if self.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and not DOMAIN_RE.fullmatch(self.value):
            raise ValueError(f"Invalid domain: {self.value}")
        if self.kind == "DOMAIN-REGEX":
            re.compile(self.value)
        if self.kind in {"IP-CIDR", "IP-CIDR6"}:
            network = ipaddress.ip_network(self.value, strict=True)
            if network.version != (6 if self.kind == "IP-CIDR6" else 4):
                raise ValueError(f"Wrong IP family: {self.text}")

    def matches(self, domain: str) -> bool:
        domain = domain.lower().rstrip(".")
        if self.kind == "DOMAIN":
            return domain == self.value
        if self.kind == "DOMAIN-SUFFIX":
            return domain == self.value or domain.endswith("." + self.value)
        if self.kind == "DOMAIN-REGEX":
            return re.search(self.value, domain, re.I) is not None
        if self.kind == "DOMAIN-WILDCARD":
            return fnmatch.fnmatchcase(domain, self.value)
        return False


def parse_v2fly(text: str):
    """Return (rule-or-include, attributes); fail closed on unknown syntax."""
    for number, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        token, *attrs = line.split()
        if any(not re.fullmatch(r"@[\w!-]+", attr) for attr in attrs):
            raise ValueError(f"Unsupported attributes at line {number}: {line}")
        prefix, colon, value = token.partition(":")
        if not colon:
            prefix, value = "domain", token
        if prefix == "include":
            if attrs:
                raise ValueError("Filtered include requires explicit implementation, not silent expansion")
            if not re.fullmatch(r"[a-z0-9!_-]+", value):
                raise ValueError(f"Unsafe include name: {value}")
            yield value, set()
            continue
        if prefix not in TYPES:
            raise ValueError(f"Unknown v2fly prefix: {prefix}")
        rule = Rule(TYPES[prefix], value if prefix == "regexp" else value.lower())
        rule.validate()
        yield rule, set(attrs)


def load_source(data: Path, name: str, stack=()):
    if not re.fullmatch(r"[a-z0-9!_-]+", name):
        raise ValueError(f"Unsafe source name: {name}")
    if name in stack:
        raise ValueError(f"Include cycle: {stack + (name,)}")
    for rule, attrs in parse_v2fly((data / name).read_text(encoding="utf-8")):
        if isinstance(rule, str):
            yield from load_source(data, rule, stack + (name,))
        else:
            yield rule, attrs, name


def load_explicit_source(data: Path, name: str):
    """Read only rules written in this file; select-mode never inherits includes."""
    if not re.fullmatch(r"[a-z0-9!_-]+", name):
        raise ValueError(f"Unsafe source name: {name}")
    for rule, attrs in parse_v2fly((data / name).read_text(encoding="utf-8")):
        if not isinstance(rule, str):
            yield rule, attrs, name


def collect(catalog, patches, data: Path, review_mode=False, selection_issues=None):
    """One entry per vendor/tier/rule, retaining all source evidence."""
    entries = {}
    ids = [v["id"] for v in catalog["vendors"]]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z0-9-]+", x) for x in ids):
        raise ValueError("Invalid or duplicate vendor ID")

    def add(vendor, tier, rule, evidence):
        rule.validate()
        if not review_mode and rule.kind not in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-REGEX"}:
            raise ValueError(f"Domain candidate needs manual handling: {rule.text}")
        if not review_mode and tier == "core" and forbidden_core(rule.value):
            raise ValueError(f"Shared/broad host forbidden in core: {rule.text}")
        entries.setdefault((vendor, tier, rule), set()).add(evidence)

    for vendor in catalog["vendors"]:
        vid = vendor["id"]
        if vendor["group"] not in {"global", "cn"}:
            raise ValueError(f"Unknown group: {vid}")
        dropped = patches.get("drop", {}).get(vid, {})
        for source in vendor.get("sources", []):
            for rule, attrs, origin in load_source(data, source):
                if "@ads" in attrs or rule.text in dropped:
                    continue
                add(vid, "core", rule, f"v2fly:data/{origin}")
        for source, selected in vendor.get("select", {}).items():
            available = {r.value: (r, attrs, origin) for r, attrs, origin in load_explicit_source(data, source)}
            for value in selected:
                if value not in available:
                    if review_mode:
                        if selection_issues is not None:
                            selection_issues.append({"vendor": vid, "source": source, "value": value,
                                                     "reason": "selected-upstream-domain-disappeared-or-moved"})
                        continue
                    raise ValueError(f"Selected upstream domain disappeared or moved behind include: {vid} {value}")
                rule, attrs, origin = available[value]
                if "@ads" in attrs or rule.text in dropped:
                    continue
                add(vid, "core", rule, f"v2fly:data/{origin} (selected explicit rule)")
    for patch in patches["add"]:
        if patch["vendor"] not in ids or patch["tier"] != "core":
            raise ValueError(f"Invalid patch target: {patch}")
        if not patch["source"].startswith("https://") or not patch["reason"]:
            raise ValueError("Patch requires HTTPS evidence and reason")
        add(patch["vendor"], "core", Rule.from_text(patch["rule"]), patch["source"] + " " + patch["reason"])
    for vid in ids:
        if not review_mode and not any(v == vid and t == "core" for v, t, _ in entries):
            raise ValueError(f"Empty core vendor: {vid}")
    return entries


def validate_profiles(catalog):
    profiles = catalog.get("profiles", {})
    expected = {"ai-daily": "global", "ai-core": "global", "ai-cn": "cn"}
    if set(profiles) != set(expected):
        raise ValueError("Catalog must define exactly ai-daily, ai-core and ai-cn profiles")
    groups = {vendor["id"]: vendor["group"] for vendor in catalog["vendors"]}
    for name, required_group in expected.items():
        spec = profiles[name]
        members = spec.get("members", [])
        budget = spec.get("budget")
        if not isinstance(budget, int) or budget < 1 or len(members) > budget:
            raise ValueError(f"Profile vendor budget exceeded or invalid: {name}")
        if not members or len(members) != len(set(members)):
            raise ValueError(f"Invalid profile membership: {name}")
        unknown = set(members) - set(groups)
        if unknown or any(groups[vendor] != required_group for vendor in members):
            raise ValueError(f"Profile contains unknown/wrong-group vendor: {name}")
    if not set(profiles["ai-daily"]["members"]).issubset(profiles["ai-core"]["members"]):
        raise ValueError("ai-daily vendors must be a subset of ai-core")
    if set(profiles["ai-core"]["members"]) != {vendor for vendor, group in groups.items() if group == "global"}:
        raise ValueError("Every maintained global vendor must have explicit ai-core membership")
    if set(profiles["ai-cn"]["members"]) != {vendor for vendor, group in groups.items() if group == "cn"}:
        raise ValueError("Every maintained CN vendor must have explicit ai-cn membership")
    return profiles


def voice_rules(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("prefixes"), list):
        raise ValueError("Unexpected OpenAI voice JSON schema")
    result = set()
    for entry in payload["prefixes"]:
        if not isinstance(entry, dict):
            raise ValueError("Voice prefix entry must be an object")
        keys = set(entry) & {"ipv4Prefix", "ipv6Prefix"}
        if len(keys) != 1:
            raise ValueError(f"Invalid voice prefix entry: {entry}")
        key = next(iter(keys))
        if not isinstance(entry[key], str):
            raise ValueError("Voice prefix must be a CIDR string")
        net = ipaddress.ip_network(entry[key], strict=True)
        if net.version != (4 if key == "ipv4Prefix" else 6):
            raise ValueError("Voice address family mismatch")
        endpoints = (net.network_address, net.broadcast_address)
        if net.prefixlen < (16 if net.version == 4 else 32) or any(
            not address.is_global or address.is_multicast or address.is_reserved
            for address in endpoints
        ):
            raise ValueError(f"Suspicious voice range: {net}")
        result.add(Rule("IP-CIDR" if net.version == 4 else "IP-CIDR6", str(net)))
    if not 1 <= len(result) <= 512:
        raise ValueError("Empty or unexpectedly large voice list")
    return result


def verify_snapshot(snapshot: Path):
    lock = read_json(snapshot / "lock.json")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["v2fly_revision"]):
        raise ValueError("Snapshot must pin an exact upstream revision")
    for relative, digest in lock["sha256"].items():
        path = (snapshot / relative).resolve()
        if not path.is_relative_to(snapshot.resolve()) or sha256(path.read_bytes()) != digest:
            raise ValueError(f"Snapshot integrity failure: {relative}")
    actual = {str(p.relative_to(snapshot)).replace("\\", "/") for p in snapshot.rglob("*") if p.is_file() and p.name != "lock.json"}
    if actual != set(lock["sha256"]):
        raise ValueError("Untracked or missing snapshot files")
    if lock["sha256"].get("V2FLY-LICENSE") != REVIEWED_V2FLY_LICENSE:
        raise ValueError("Upstream license changed; review terms before accepting a new snapshot")
    return lock


def render_rule(rule, target, patches):
    if rule.kind == "DOMAIN-REGEX" and target == "surge":
        adapter = patches["surge_regex"].get(rule.value)
        if adapter is None:
            raise ValueError(f"Unreviewed Surge regex conversion: {rule.value}")
        translated = Rule.from_text(adapter["rule"])
        if translated.kind != "DOMAIN-WILDCARD" or not translated.value.endswith(".webpubsub.azure.com"):
            raise ValueError("Unsafe Surge adapter")
        return translated.text
    if rule.kind in {"IP-CIDR", "IP-CIDR6"}:
        return f"{rule.kind},{rule.value},no-resolve"
    return rule.text


def render_members(members, target, patches, catalog):
    """Group by vendor and keep subscription files compact.

    Detailed provenance and retained-state evidence live in manifest/report data.
    """
    vendors = {v["id"]: v["name"] for v in catalog["vendors"]}
    order = {v["id"]: index for index, v in enumerate(catalog["vendors"])}
    records = {}
    for (vendor, tier, rule), _origins in members.items():
        line = render_rule(rule, target, patches)
        record = records.setdefault(line, {"owners": set()})
        record["owners"].add((vendor, tier))
    sections = {}
    for line, record in records.items():
        owners = tuple(sorted(record["owners"], key=lambda owner: (owner[1] == "voice", order[owner[0]])))
        sections.setdefault(owners, []).append(line)
    lines = ["payload:"] if target == "mihomo" else []
    indent = "  " if target == "mihomo" else ""

    def comment(value):
        lines.append(indent + "# " + value)

    ordered_sections = sorted(
        sections.items(),
        key=lambda item: (item[0][0][1] == "voice", order[item[0][0][0]], item[0]),
    )
    show_sections = len(ordered_sections) > 1
    for owners, rule_lines in ordered_sections:
        if show_sections:
            lines.append("")
            labels = [vendors[v] + (" 语音" if tier == "voice" else "") for v, tier in owners]
            comment(" / ".join(labels))
        for line in sorted(rule_lines):
            lines.append(line if target == "surge" else "  - " + json.dumps(line))
    return "\n".join(lines) + "\n", len(records)


def subscription_index(catalog):
    lines = ["# 订阅目录", "", "日常使用推荐 `ai-daily`。以下为 `stable` 规则文件，不包含代理节点。", "",
             "<!-- 本页由 scripts/rules.py 自动生成，请勿手改。 -->", "",
             "## 合集", "", "| 规则集 | 用途 | Surge | Mihomo / FlClash |", "| --- | --- | --- | --- |"]
    def row(name, description):
        return f"| {name} | {description} | [订阅]({RAW_URL}/rules/surge/{name}.list) | [订阅]({RAW_URL}/rules/mihomo/{name}.yaml) |"
    for name in ("ai-daily", "ai-core", "ai-cn"):
        lines.append(row(name, f"{len(catalog['profiles'][name]['members'])} 家厂商。{BUNDLE_DESCRIPTIONS[name]}"))
    daily = catalog["profiles"]["ai-daily"]["members"]
    lines += ["", "使用 `ai-core` 或单厂商 `openai` 且需要语音时，另加 `openai-voice-ip` 并设置相同策略。", "",
              "日常厂商：" + "、".join(daily) + "。", "",
              "## 单厂商", "", "仅含核心域名。需要独立出口时选用，并放在合集前。", ""]
    for group, title in (("global", "海外服务"), ("cn", "国内服务")):
        lines += [f"### {title}", "", "| 文件 | 服务 | Surge | Mihomo / FlClash |", "| --- | --- | --- | --- |"]
        for vendor in catalog["vendors"]:
            if vendor["group"] == group:
                lines.append(row(vendor["id"], vendor["name"]))
        lines.append("")
    lines += ["## 可选功能包", "", "| 文件 | 功能 | Surge | Mihomo / FlClash |", "| --- | --- | --- | --- |",
              row("openai-voice-ip", BUNDLE_DESCRIPTIONS["openai-voice-ip"]), "",
              "规则范围与客户端差异见 [格式兼容](../docs/COMPATIBILITY.md)。", "",
              "[返回首页](../README.md) · [Surge 示例](../examples/surge-daily.conf) · [FlClash 示例](../examples/flclash-daily.yaml)", ""]
    return "\n".join(lines)


def compile_outputs(root: Path, snapshot: Path | None = None, automation_state=None):
    from automation import effective_entries, scope_problem
    snapshot = snapshot or root / "sources" / "snapshot"
    lock = verify_snapshot(snapshot)
    catalog = read_json(root / "sources/catalog.json")
    profiles = validate_profiles(catalog)
    contracts = read_json(root / "sources/semantic-contracts.json")
    if contracts.get("schema") != 2 or set(contracts.get("vendors", {})) != {v["id"] for v in catalog["vendors"]}:
        raise ValueError("New candidates require schema 2 contracts for every maintained vendor")
    patches = read_json(root / "sources/patches.json")
    selection_issues = []
    candidates = collect(catalog, patches, snapshot / "v2fly", review_mode=True, selection_issues=selection_issues)
    state = automation_state if automation_state is not None else read_json(root / "sources/automation-state.json")
    entries = effective_entries(candidates, catalog, patches, state)
    for issue in selection_issues:
        if not any(
            vendor == issue["vendor"] and tier == "core" and rule.matches(issue["value"])
            for vendor, tier, rule in entries
        ):
            raise ValueError(
                f"Selected upstream domain lost effective coverage: {issue['vendor']} {issue['value']}"
            )
    bundles = {v["id"]: {} for v in catalog["vendors"]}
    bundles.update({"ai-core": {}, "ai-cn": {}, "ai-daily": {}})
    for key, origins in entries.items():
        vendor, tier, rule = key
        if tier != "core":
            raise ValueError(f"Unexpected non-core production rule: {vendor}/{tier}/{rule.text}")
        destinations = [vendor]
        for profile in ("ai-core", "ai-cn", "ai-daily"):
            if vendor in profiles[profile]["members"]:
                destinations.append(profile)
        for destination in destinations:
            bundles[destination][key] = origins
    bundles["openai-voice-ip"] = {("openai", "voice", rule): {lock["voice_url"]} for rule in voice_rules(read_json(snapshot / "openai-voice.json"))}
    bundles["ai-daily"].update(bundles["openai-voice-ip"])
    warnings = [
        {"rule": rule.text, "surge": patches["surge_regex"][rule.value]}
        for rule in sorted({r for _, _, r in entries if r.kind == "DOMAIN-REGEX"})
    ]
    files = {}
    manifest = {
        "schema": 2, "upstream": lock, "vendor_count": len(catalog["vendors"]),
        "license": "AGPL-3.0-only (retained MIT notices; official facts keep source terms)",
        "formats": {"surge": "rule-set", "mihomo": "classical/yaml (FlClash)"},
        "conversion_warnings": warnings, "bundles": {},
        "profiles": {name: {"members": list(profiles[name]["members"]), "budget": profiles[name]["budget"]}
                     for name in ("ai-daily", "ai-core", "ai-cn")},
        "profile_features": {"ai-daily": ["openai-voice-ip"]},
        "semantic_contract": {
            "path": "sources/semantic-contracts.json",
            "sha256": sha256((root / "sources/semantic-contracts.json").read_bytes())
        },
        "automation": {
            "quarantined": [
                dict(vendor=v, tier=t, rule=r.text, reason=scope_problem((v, t, r), candidates[(v, t, r)], catalog, patches))
                for v, t, r in sorted(candidates)
                if scope_problem((v, t, r), candidates[(v, t, r)], catalog, patches)
            ],
            "selection_issues": selection_issues,
            "retained": state.get("retained", [])
        },
        "client_validation": "See docs/VALIDATION.md; generation is not a connectivity test"
    }
    for name, members in sorted(bundles.items()):
        active_rules = {rule for _, _, rule in members}
        if not active_rules:
            raise ValueError(f"Refusing empty bundle: {name}")
        paths = {}
        for target, ext in (("surge", "list"), ("mihomo", "yaml")):
            body, count = render_members(members, target, patches, catalog)
            description = BUNDLE_DESCRIPTIONS.get(name, "单厂商核心域名；不含共享依赖和语音 IP。")
            header = (
                f"# NET86/rules | {name}\n"
                f"# {description}\n"
                f"# 自动生成，请勿手改。清单：{RAW_URL}/rules/manifest.json\n"
                "# SPDX-License-Identifier: AGPL-3.0-only\n"
                f"# 第三方声明：{PROJECT_URL}/blob/main/THIRD_PARTY_NOTICES.md\n"
            )
            if target == "surge" and any(r.kind == "DOMAIN-REGEX" for r in active_rules):
                header += "# 注意：此通配符比上游正则更宽，详见 docs/COMPATIBILITY.md\n"
            text = header + body
            path = f"rules/{target}/{name}.{ext}"
            files[path] = text
            paths[target] = {"path": path, "sha256": sha256(text.encode()), "count": count}
        manifest["bundles"][name] = paths
    manifest["provenance"] = [
        {"vendor": v, "tier": t, "rule": r.text, "sources": sorted(origins)}
        for (v, t, r), origins in sorted(entries.items())
    ]
    files["rules/manifest.json"] = json_text(manifest)
    files["rules/README.md"] = subscription_index(catalog)
    return files


def publish_files(root: Path, files):
    # Compilation/validation completes before any generated output is touched.
    expected = set(files)
    current = {p.relative_to(root).as_posix() for p in (root / "rules").rglob("*") if p.is_file()}
    stale = current - expected
    for relative in sorted(stale):
        if not re.fullmatch(r"rules/(?:surge|mihomo)/[a-z0-9-]+\.(?:list|yaml)", relative):
            raise ValueError(f"Unexpected stale file needs explicit review: {relative}")
        (root / relative).unlink()
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify committed artifacts, offline")
    args = parser.parse_args()
    try:
        files = compile_outputs(ROOT)
        if args.check:
            actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / "rules").rglob("*") if p.is_file()}
            if actual != set(files):
                raise ValueError("Generated file set mismatch")
            for path, text in files.items():
                if (ROOT / path).read_bytes() != text.encode():
                    raise ValueError(f"Stale generated output: {path}")
        else:
            publish_files(ROOT, files)
        print(f"OK: {len(files)} deterministic output files")
    except (ValueError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
