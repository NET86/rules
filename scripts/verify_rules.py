"""Independent portable artifact and semantic-contract verification gate."""
from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
import re
import subprocess
import tempfile
from pathlib import Path

from rules import ROOT, sha256, read_json, json_text

HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def parse_artifact(data, target):
    text = data.decode("utf-8-sig")
    active = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if target == "mihomo":
        if not active or active[0] != "payload:" or any(not line.startswith("  - ") for line in active[1:]):
            raise ValueError("Unsupported Mihomo YAML shape")
        active = [json.loads(line[4:]) for line in active[1:]]
    parsed = []
    for line in active:
        if not isinstance(line, str):
            raise ValueError("Non-string rule")
        fields = line.split(",")
        if len(fields) not in {2, 3}:
            raise ValueError("Invalid rule field count")
        kind, value = fields[:2]
        if kind in {"IP-CIDR", "IP-CIDR6"}:
            network = ipaddress.ip_network(value, strict=True)
            if fields[2:] != ["no-resolve"] or network.version != (4 if kind == "IP-CIDR" else 6):
                raise ValueError("Unsafe IP rule/options")
        elif len(fields) != 2:
            raise ValueError("Unexpected domain rule options")
        elif kind in {"DOMAIN", "DOMAIN-SUFFIX"}:
            if not HOST.fullmatch(value):
                raise ValueError("Invalid domain syntax")
        elif kind == "DOMAIN-REGEX" and target == "mihomo":
            re.compile(value)
        elif kind == "DOMAIN-WILDCARD" and target == "surge":
            if value != "chatgpt-async-webps-prod-*-*.webpubsub.azure.com":
                raise ValueError("Undeclared Surge wildcard")
        else:
            raise ValueError(f"Unsupported portable rule: {kind}")
        parsed.append(line)
    if not parsed or len(parsed) != len(set(parsed)):
        raise ValueError("Empty/duplicate active rules")
    return parsed


def domain_matches(line, host):
    kind, value, *_ = line.split(",")
    host = host.lower().rstrip(".")
    if kind == "DOMAIN":
        return host == value
    if kind == "DOMAIN-SUFFIX":
        return host == value or host.endswith("." + value)
    if kind == "DOMAIN-REGEX":
        return re.search(value, host, re.I) is not None
    if kind == "DOMAIN-WILDCARD":
        return fnmatch.fnmatchcase(host, value)
    return False


def check_cases(label, rules, contract):
    for host in contract.get("must_match", []):
        if not any(domain_matches(line, host) for line in rules):
            raise ValueError(f"Semantic contract miss: {label} must match {host}")
    for host in contract.get("must_not_match", []):
        if any(domain_matches(line, host) for line in rules):
            raise ValueError(f"Semantic contract false positive: {label} matched {host}")


def load_contracts(root, manifest):
    spec = manifest.get("semantic_contract")
    if not spec:
        raise ValueError("Missing required manifest profile/semantic contract")
    if spec.get("path") != "sources/semantic-contracts.json":
        raise ValueError("Unexpected semantic contract path")
    path = root / spec["path"]
    data = path.read_bytes()
    if sha256(data) != spec["sha256"]:
        raise ValueError("Semantic contract digest mismatch")
    contracts = json.loads(data)
    if not isinstance(contracts, dict):
        raise ValueError("Invalid semantic contract structure")
    profiles = contracts.get("profiles", {})
    vendors = contracts.get("vendors", {})
    if contracts.get("schema") != 1 or not isinstance(profiles, dict) or not isinstance(vendors, dict):
        raise ValueError("Invalid semantic contract structure")
    if set(profiles) != {"ai-daily", "ai-core", "ai-cn"}:
        raise ValueError("Missing required semantic contract profiles")
    daily = manifest["profiles"]["ai-daily"]["members"]
    if not vendors or not set(daily).issubset(vendors):
        raise ValueError("Missing required daily vendor semantic contracts")
    for label, contract in list(vendors.items()) + list(profiles.items()):
        if not isinstance(contract, dict):
            raise ValueError(f"Invalid semantic contract: {label}")
        for field in ("must_match", "must_not_match"):
            hosts = contract.get(field)
            if not isinstance(hosts, list) or not hosts or any(
                not isinstance(host, str) or not HOST.fullmatch(host) for host in hosts
            ) or len(hosts) != len(set(hosts)):
                raise ValueError(f"Empty/invalid semantic cases: {label}/{field}")
        if set(contract["must_match"]) & set(contract["must_not_match"]):
            raise ValueError(f"Contradictory semantic cases: {label}")
    return contracts


def semantic_contract(root, manifest, parsed_bundles):
    contracts = load_contracts(root, manifest)

    # Contracts must exercise the actual standalone vendor artifacts, not the
    # generator's provenance declaration. This keeps the semantic oracle
    # independent from the manifest state it is meant to catch.
    for vendor, contract in contracts.get("vendors", {}).items():
        if vendor not in parsed_bundles:
            raise ValueError(f"Semantic contract vendor artifact missing: {vendor}")
        for target in ("surge", "mihomo"):
            check_cases(f"vendor/{vendor}/{target}", parsed_bundles[vendor][target], contract)

    for profile, contract in contracts.get("profiles", {}).items():
        if profile not in parsed_bundles:
            raise ValueError(f"Semantic contract profile missing: {profile}")
        for target in ("surge", "mihomo"):
            check_cases(f"{profile}/{target}", parsed_bundles[profile][target], contract)
    return "PASS"


def profile_equivalence(manifest, parsed_bundles):
    """Independently prove each aggregate is exactly its declared members/features."""
    profiles = manifest.get("profiles")
    if not profiles:
        raise ValueError("Missing required manifest profile/semantic contract")
    if set(profiles) != {"ai-daily", "ai-core", "ai-cn"}:
        raise ValueError("Unexpected profile set")
    features = manifest.get("profile_features", {})
    for profile, spec in profiles.items():
        members = spec.get("members", [])
        if profile not in parsed_bundles or not members:
            raise ValueError(f"Invalid profile declaration: {profile}")
        additions = features.get(profile, [])
        for target in ("surge", "mihomo"):
            expected = set()
            for name in list(members) + list(additions):
                if name not in parsed_bundles:
                    raise ValueError(f"Profile member artifact missing: {profile}/{name}")
                expected.update(parsed_bundles[name][target])
            actual = set(parsed_bundles[profile][target])
            if actual != expected:
                missing = sorted(expected - actual)[:5]
                extra = sorted(actual - expected)[:5]
                raise ValueError(f"Profile composition mismatch: {profile}/{target}; missing={missing}; extra={extra}")
    return "PASS"


def verify(root, surge_cli=None):
    manifest = read_json(root / "rules/manifest.json")
    checked = 0
    parsed_bundles = {}
    for name, targets in manifest["bundles"].items():
        values = {}
        for target, spec in targets.items():
            path = (root / spec["path"]).resolve()
            if not path.is_relative_to((root / "rules").resolve()):
                raise ValueError("Artifact path escapes rules directory")
            data = path.read_bytes()
            values[target] = parse_artifact(data, target)
            if sha256(data) != spec["sha256"] or len(values[target]) != spec["count"]:
                raise ValueError(f"Artifact hash/count mismatch: {name}/{target}")
            if manifest.get("license", "").startswith("AGPL-3.0-only") and (
                b"SPDX-License-Identifier: AGPL-3.0-only" not in data or b"THIRD_PARTY_NOTICES.md" not in data
            ):
                raise ValueError("Missing compact license notice")
            checked += 1
        expected = set(values["mihomo"])
        for warning in manifest["conversion_warnings"]:
            if warning["rule"] in expected:
                expected.remove(warning["rule"])
                expected.add(warning["surge"]["rule"])
        if set(values["surge"]) != expected:
            raise ValueError(f"Undeclared format divergence: {name}")
        parsed_bundles[name] = values
        if surge_cli:
            with tempfile.TemporaryDirectory(prefix="surge-parse-") as td:
                lines = []
                for line in values["surge"]:
                    fields = line.split(",")
                    lines.append(",".join(fields[:2] + ["REJECT"] + fields[2:]))
                config = Path(td) / "isolated.conf"
                config.write_text("[General]\nloglevel = warning\n[Rule]\n" + "\n".join(lines) + "\nFINAL,REJECT\n", encoding="utf-8")
                subprocess.run([str(surge_cli), "--check", str(config)], check=True, timeout=30, capture_output=True)

    composition = profile_equivalence(manifest, parsed_bundles)
    semantic = semantic_contract(root, manifest, parsed_bundles)
    return {
        "result": "PASS",
        "artifact_count": checked,
        "profile_equivalence": composition,
        "semantic_contract": semantic,
        "semantic_case_count": sum(
            len(contract[field])
            for name, group in load_contracts(root, manifest).items() if name in {"vendors", "profiles"}
            for contract in group.values() for field in ("must_match", "must_not_match")
        ),
        "surge_native": "PASS" if surge_cli else "NOT_RUN",
        "scope": "Portable syntax/hash/count/cross-format, exact profile composition and independent semantic-contract gate; not AI account connectivity",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--surge-cli", type=Path)
    args = parser.parse_args()
    report = verify(args.root.resolve(), args.surge_cli)
    work = args.root / ".work"
    work.mkdir(exist_ok=True)
    (work / "portable-validation.json").write_text(json_text(report), encoding="utf-8")
    print(json_text(report))


if __name__ == "__main__":
    main()
