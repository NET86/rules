#!/usr/bin/env python3
"""Fetch production inputs into a disposable stage; validate before updating artifacts."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from automation import effective_entries, reconcile
from intake import analyze_official, refresh_official
from rules import (
    ROOT,
    collect,
    compile_outputs,
    json_text,
    parse_v2fly,
    publish_files,
    read_json,
    sha256,
    voice_rules,
    verify_snapshot,
)

VOICE_URL = "https://openai.com/chatgpt-voice.json"


def fetch(url: str, limit=4_000_000, attempts=3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "NET86-rules/1.0", "Accept": "*/*"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read(limit + 1)
            if not data or len(data) > limit:
                raise ValueError(f"Empty or oversized upstream response: {url}")
            return data
        except (OSError, ValueError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (2 ** attempt))
    raise ValueError("No download attempts configured")


def fetch_voice(root: Path):
    try:
        payload = fetch(VOICE_URL)
        voice_rules(json.loads(payload))
        return payload, "fresh"
    except (OSError, ValueError) as exc:
        snapshot = root / "sources/snapshot"
        verify_snapshot(snapshot)
        payload = (snapshot / "openai-voice.json").read_bytes()
        voice_rules(json.loads(payload))
        print(f"WARNING: official voice fetch failed ({type(exc).__name__}); keeping verified last-good voice IPs")
        return payload, "retained-last-good"


def snapshot_from_repo(repo: Path, snapshot: Path, catalog, voice: bytes):
    """Export only consumed v2fly surfaces; select files never inherit includes."""
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    data = snapshot / "v2fly"
    data.mkdir(parents=True)
    recursive_names = {name for vendor in catalog["vendors"] for name in vendor.get("sources", [])}
    explicit_names = {name for vendor in catalog["vendors"] for name in vendor.get("select", {})}
    written, expanded = set(), set()

    def export(name, recurse):
        if not re.fullmatch(r"[a-z0-9!_-]+", name):
            raise ValueError(f"Unsafe source: {name}")
        if name not in written:
            content = subprocess.check_output(["git", "-C", str(repo), "show", f"{revision}:data/{name}"])
            text = content.decode("utf-8")
            (data / name).write_text(text, encoding="utf-8", newline="\n")
            written.add(name)
        else:
            text = (data / name).read_text(encoding="utf-8")
        if not recurse or name in expanded:
            return
        expanded.add(name)
        for rule, _ in parse_v2fly(text):
            if isinstance(rule, str):
                export(rule, True)

    for name in sorted(recursive_names):
        export(name, True)
    for name in sorted(explicit_names):
        export(name, False)

    license_text = subprocess.check_output(["git", "-C", str(repo), "show", f"{revision}:LICENSE"])
    (snapshot / "V2FLY-LICENSE").write_bytes(license_text)
    voice_rules(json.loads(voice))
    (snapshot / "openai-voice.json").write_text(json_text(json.loads(voice)), encoding="utf-8", newline="\n")
    lock = {
        "v2fly_repository": "https://github.com/v2fly/domain-list-community",
        "v2fly_revision": revision,
        "voice_url": VOICE_URL,
        "sha256": {
            p.relative_to(snapshot).as_posix(): sha256(p.read_bytes())
            for p in sorted(snapshot.rglob("*")) if p.is_file()
        },
    }
    (snapshot / "lock.json").write_text(json_text(lock), encoding="utf-8", newline="\n")


def stabilize_lock(root: Path, snapshot: Path):
    """Keep the lock content-addressed; transient health belongs in run reports."""
    path = snapshot / "lock.json"
    lock = read_json(path)
    old_path = root / "sources/snapshot/lock.json"
    if old_path.exists():
        old = read_json(old_path)
        only_v2fly = lambda data: {key: value for key, value in data["sha256"].items() if key != "openai-voice.json"}
        if only_v2fly(old) == only_v2fly(lock):
            lock["v2fly_revision"] = old["v2fly_revision"]
    path.write_text(json_text(lock), encoding="utf-8", newline="\n")


def commit_stage(root: Path, snapshot: Path, files):
    """Replace the deterministic consumed snapshot and generated rule surface."""
    destination = root / "sources/snapshot"
    destination.mkdir(parents=True, exist_ok=True)
    staged = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    old = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    for relative in sorted(old - staged):
        target = (destination / relative).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise ValueError("Unsafe snapshot cleanup path")
        target.unlink()
    for relative in sorted(staged):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((snapshot / relative).read_bytes())
    publish_files(root, files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, help="Use an existing v2fly git repository")
    parser.add_argument("--voice-file", type=Path, help="Use a previously fetched OFFICIAL voice JSON")
    parser.add_argument("--allow-reviewed-removals", action="store_true", help="Skip time buffer after a healthy observation; semantic protection remains")
    args = parser.parse_args()
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="sync-", dir=work) as temporary:
            stage = Path(temporary)
            official_state, official_fetch_report = refresh_official(ROOT, fetch)
            repo = args.source_repo.resolve() if args.source_repo else stage / "v2fly-repo"
            snapshot = stage / "snapshot"
            voice, voice_status = (args.voice_file.read_bytes(), "fresh") if args.voice_file else fetch_voice(ROOT)
            catalog = read_json(ROOT / "sources/catalog.json")
            patches = read_json(ROOT / "sources/patches.json")
            contracts = read_json(ROOT / "sources/semantic-contracts.json")
            v2fly_errors = []
            v2fly_fresh = True
            try:
                if not args.source_repo:
                    subprocess.run(
                        ["git", "clone", "--depth", "1", "https://github.com/v2fly/domain-list-community.git", str(repo)],
                        check=True, timeout=180,
                    )
                snapshot_from_repo(repo, snapshot, catalog, voice)
                verify_snapshot(snapshot)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if args.source_repo:
                    raise
                v2fly_fresh = False
                verify_snapshot(ROOT / "sources/snapshot")
                snapshot = stage / "snapshot-last-good"
                shutil.copytree(ROOT / "sources/snapshot", snapshot)
                (snapshot / "openai-voice.json").write_text(json_text(json.loads(voice)), encoding="utf-8", newline="\n")
                lock = read_json(snapshot / "lock.json")
                lock["sha256"]["openai-voice.json"] = sha256((snapshot / "openai-voice.json").read_bytes())
                (snapshot / "lock.json").write_text(json_text(lock), encoding="utf-8", newline="\n")
                v2fly_errors.append({
                    "source_id": "v2fly", "reason": "v2fly-unavailable-or-license-changed",
                    "error_type": type(exc).__name__, "action": "Retained verified snapshot; deletion observations frozen",
                })
            stabilize_lock(ROOT, snapshot)

            selection_issues = []
            entries = collect(catalog, patches, snapshot / "v2fly", review_mode=True, selection_issues=selection_issues)
            unhealthy_vendors = {row["vendor"] for row in selection_issues}
            previous = read_json(ROOT / "rules/manifest.json") if (ROOT / "rules/manifest.json").exists() else {}
            previous_state = read_json(ROOT / "sources/automation-state.json")
            state, report = reconcile(
                entries, previous, catalog, patches, previous_state,
                read_json(ROOT / "sources/automation.json"),
                today=datetime.now(timezone.utc).date(),
                allow_removals=args.allow_reviewed_removals,
                contracts=contracts,
                source_observation_healthy=v2fly_fresh,
                unhealthy_vendors=unhealthy_vendors,
            )

            effective = effective_entries(entries, catalog, patches, state)
            official_radar = analyze_official(ROOT, official_state, effective)
            report["source_health"] = {
                "v2fly": "fresh" if v2fly_fresh else "retained-last-good",
                "openai_voice": voice_status,
                "official_facts": official_fetch_report["sources"],
            }
            report["official_radar"] = official_radar
            if voice_status != "fresh":
                report["review_required"].append({
                    "reason": "official-voice-fetch-unavailable", "source": VOICE_URL,
                    "action": "Verified last-good IPs retained; domain updates continue; auto-clears when fetch recovers",
                })
            report["review_required"].extend(
                official_fetch_report["review_required"] + v2fly_errors + selection_issues + official_radar["review_required"]
            )
            (work / "sync-report.json").write_text(json_text(report), encoding="utf-8", newline="\n")

            files = compile_outputs(ROOT, snapshot, state)
            commit_stage(ROOT, snapshot, files)
            # Persist the latest successfully parsed official fact baseline. This file
            # has no run timestamp, so unchanged facts produce no commit noise. Stable
            # promotion still depends on the generated manifest, not radar-only state.
            (ROOT / "sources/official-state.json").write_text(json_text(official_state), encoding="utf-8", newline="\n")
            (ROOT / "sources/automation-state.json").write_text(json_text(state), encoding="utf-8", newline="\n")
            print(f"OK: synchronized {len(files)} artifacts after scope, schema and integrity checks")
            print(f"Exceptions: {len(report['review_required'])}; quarantined: {report['quarantined_count']}; retained: {report['retained_count']}")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        (work / "sync-error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        print(f"SYNC BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
