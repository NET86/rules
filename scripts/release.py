#!/usr/bin/env python3
"""Validated, fast-forward-only stable publication with an automatic forward rollback."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rules import ROOT, json_text, sha256
from sync import fetch
from verify_rules import verify

AUTO_PATHS = ["sources/snapshot", "sources/official-state.json", "sources/automation-state.json", "rules"]


class Publisher:
    def __init__(self, root, remote="origin"):
        self.root, self.remote = Path(root), remote

    def git(self, *args, input=None, env=None):
        return subprocess.check_output(["git", "-C", str(self.root), *args], input=input,
                                       text=True, encoding="utf-8", timeout=120, env=env).strip()

    def remote_ref(self, branch):
        rows = self.git("ls-remote", "--heads", self.remote, f"refs/heads/{branch}")
        return rows.split()[0] if rows else None

    def obtain(self, revision):
        self.git("fetch", "--no-tags", self.remote, revision)

    def tree(self, revision):
        return self.git("rev-parse", f"{revision}^{{tree}}")

    def commit_tree(self, tree, parents, message):
        args = ["commit-tree", tree]
        for parent in dict.fromkeys(parents):
            args += ["-p", parent]
        return self.git(*args, input=message + "\n")

    def same_release(self, candidate, stable):
        """A stable publication is meaningful only when its generated manifest changes."""
        return self.git("show", f"{candidate}:rules/manifest.json") == self.git("show", f"{stable}:rules/manifest.json")

    def require_refs(self, expected):
        for branch, revision in expected.items():
            if self.remote_ref(branch) != revision:
                raise RuntimeError(f"Concurrent {branch} update; refusing to overwrite it")

    def recover_stable(self, validate, report):
        """Next-run repair if a runner/network died before completing rollback."""
        stable = self.remote_ref("stable")
        lkg = self.remote_ref("last-known-good")
        if not stable or not lkg:
            raise RuntimeError("Missing verified release branches")
        self.obtain(stable)
        self.obtain(lkg)
        try:
            validate("stable", stable)
            report["stable_preflight"] = "PASS"
            return
        except Exception as exc:
            report["stable_preflight_error"] = str(exc)
        # Never replace one unverified version with another. A widespread raw
        # service outage will fail here and leave the branch untouched.
        validate(lkg, lkg)
        self.require_refs({"stable": stable, "last-known-good": lkg})
        recovered = self.commit_tree(self.tree(lkg), [stable], f"recover: last verified release {lkg}")
        self.git("push", self.remote, f"{recovered}:refs/heads/stable")
        validate("stable", lkg)
        report["stable_preflight"] = "AUTOMATICALLY_RECOVERED"

    def run(self, candidate, validate_published, report):
        """Publish main as candidate; only stable is rolled back if promotion fails."""
        old_main = self.remote_ref("main")
        old_stable = self.remote_ref("stable")
        old_lkg = self.remote_ref("last-known-good")
        if not old_stable or not old_lkg:
            raise RuntimeError("Bootstrap stable and last-known-good from a verified commit first")
        self.obtain(old_stable)
        self.obtain(old_lkg)
        report.update(candidate=candidate, previous_stable=old_stable, previous_main=old_main)
        promoted = old_stable
        try:
            self.require_refs({"main": old_main, "stable": old_stable, "last-known-good": old_lkg})
            # Main is intentionally the development/candidate branch. It remains
            # diagnostic state even if stable promotion later fails.
            if old_main != candidate:
                self.git("push", self.remote, f"{candidate}:refs/heads/main")
            validate_published(candidate, "candidate")
            report["candidate_remote_validation"] = "PASS"
            self.require_refs({"main": candidate, "stable": old_stable, "last-known-good": old_lkg})
            if not self.same_release(candidate, old_stable):
                promoted = self.commit_tree(
                    self.tree(candidate), [old_stable, candidate],
                    f"release: verified candidate {candidate}",
                )
                self.git(
                    "push", "--atomic", self.remote,
                    f"{old_stable}:refs/heads/last-known-good",
                    f"{promoted}:refs/heads/stable",
                )
            else:
                report["stable_noop"] = "UNCHANGED_GENERATED_MANIFEST"
            report["stable_revision"] = promoted
            validate_published("stable", "stable")
            self.require_refs({"stable": promoted})
            report.update(result="PASS", stable_remote_validation="PASS")
            return promoted
        except Exception as exc:
            report.update(result="FAILED", error=str(exc))
            if promoted != old_stable:
                try:
                    current = self.remote_ref("stable")
                    if current == promoted:
                        rollback = self.commit_tree(
                            self.tree(old_stable), [promoted],
                            f"rollback: restore verified {old_stable}",
                        )
                        self.git("push", self.remote, f"{rollback}:refs/heads/stable")
                        report["rollback_refs_restored"] = True
                        report["rollback"] = "RESTORED_STABLE"
                    elif current == old_stable:
                        report["rollback"] = "NOT_NEEDED_STABLE_UNCHANGED"
                    else:
                        report["rollback"] = "SKIPPED_CONCURRENT_STABLE_UPDATE"
                        report["rollback_conflicts"] = ["stable"]
                    report["stable_after_failure"] = self.remote_ref("stable")
                    if report["rollback"] != "SKIPPED_CONCURRENT_STABLE_UPDATE":
                        validate_published("stable", "rollback")
                        report["rollback_remote_validation"] = "PASS"
                except Exception as rollback_error:
                    report["rollback"] = "RESTORED_VERIFICATION_PENDING" if report.get("rollback_refs_restored") else "FAILED_REMOTE_UNAVAILABLE"
                    report["rollback_error"] = str(rollback_error)
            else:
                report["rollback"] = "NOT_NEEDED_STABLE_UNCHANGED"
            raise


def downloaded_rules(root, revision, expected, get=fetch, max_wait=420, pause=time.sleep):
    """Verify actual published content against locally validated immutable hashes."""
    if revision != "stable" and not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Unsafe release ref")
    prefix = f"https://raw.githubusercontent.com/NET86/rules/{revision}/"
    deadline = time.monotonic() + max_wait
    paths = {"rules/manifest.json": sha256(json_text(expected).encode())}
    contract = expected.get("semantic_contract")
    if contract:
        if contract.get("path") != "sources/semantic-contracts.json" or not re.fullmatch(r"[a-f0-9]{64}", contract.get("sha256", "")):
            raise ValueError("Unsafe semantic contract reference")
        paths[contract["path"]] = contract["sha256"]
    for targets in expected["bundles"].values():
        for spec in targets.values():
            path = spec["path"]
            if not re.fullmatch(r"rules/(?:surge|mihomo)/[a-z0-9-]+\.(?:list|yaml)", path):
                raise ValueError("Unsafe published artifact path")
            paths[path] = spec["sha256"]
    def one(item):
        path, digest = item
        # GitHub's ref-resolution/CDN cache can outlive a branch update even
        # with query strings. Allow bounded convergence, never accept old/mixed
        # bytes as the new release and never weaken the expected digest.
        waiting = False
        while True:
            try:
                data = get(prefix + path + "?verified=" + digest[:16])
                if sha256(data) != digest:
                    raise ValueError(f"Published artifact mismatch: {path}")
                break
            except (OSError, ValueError):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                if not waiting:
                    print(f"Waiting for raw/CDN convergence: {path}", flush=True)
                    waiting = True
                pause(min(10, remaining))
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, paths.items()))
    return len(paths)


def runtime_gate(root, binaries, profile="ai-daily"):
    verify(root)
    for label, binary in binaries:
        subprocess.run([sys.executable, str(ROOT / "scripts/verify_mihomo.py"),
                        "--root", str(root), "--binary", str(binary),
                        "--engine-label", label, "--profile", profile], check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mihomo", type=Path, default=ROOT / ".work/bin/mihomo")
    parser.add_argument("--flclash-core", type=Path)
    parser.add_argument("--recover-only", action="store_true", help="Portable stable/LKG repair before any new downloads, builds or source sync")
    args = parser.parse_args()
    if os.environ.get("GITHUB_REPOSITORY") != "NET86/rules":
        raise ValueError("Live publication is restricted to NET86/rules CI")
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    report = {"result": "RECOVERY_PREFLIGHT" if args.recover_only else "PREVALIDATING"}
    publisher = Publisher(ROOT)
    try:
        publisher.git("config", "user.name", "github-actions[bot]")
        publisher.git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")

        def portable_healthcheck(ref, expected_revision):
            expected = json.loads(publisher.git("show", f"{expected_revision}:rules/manifest.json"))
            with tempfile.TemporaryDirectory(prefix="release-portable-health-", dir=work) as td:
                target = Path(td)
                downloaded_rules(target, ref, expected)
                verify(target)

        if args.recover_only:
            publisher.recover_stable(portable_healthcheck, report)
            report["result"] = "PASS"
            return

        if args.flclash_core is None:
            raise ValueError("--flclash-core is required for full publication validation")
        binaries = [("mihomo", args.mihomo.resolve()), ("flclash-core", args.flclash_core.resolve())]

        def healthcheck(ref, expected_revision):
            expected = json.loads(publisher.git("show", f"{expected_revision}:rules/manifest.json"))
            with tempfile.TemporaryDirectory(prefix="release-health-", dir=work) as td:
                target = Path(td)
                downloaded_rules(target, ref, expected)
                runtime_gate(target, binaries)

        publisher.recover_stable(healthcheck, report)
        subprocess.run([sys.executable, "scripts/rules.py", "--check"], cwd=ROOT, check=True)
        for profile in ("ai-daily", "split"):
            runtime_gate(ROOT, binaries, profile)
        publisher.git("add", "--", *AUTO_PATHS)
        if publisher.git("diff", "--cached", "--name-only"):
            publisher.git("commit", "-m", "chore: sync verified production rules")
        if publisher.git("status", "--porcelain"):
            raise ValueError("Unexpected uncommitted changes outside automatic publication scope")
        candidate = publisher.git("rev-parse", "HEAD")
        expected = json.loads((ROOT / "rules/manifest.json").read_text(encoding="utf-8"))

        def postvalidate(revision, label):
            with tempfile.TemporaryDirectory(prefix="published-", dir=work) as td:
                target = Path(td)
                manifest = expected if label != "rollback" else json.loads(
                    publisher.git("show", f"{report['previous_stable']}:rules/manifest.json")
                )
                count = downloaded_rules(target, revision, manifest)
                runtime_gate(target, binaries)
                report[label + "_artifact_count"] = count
                for path in (target / ".work").glob("*validation*.json"):
                    (work / f"published-{label}-{path.name}").write_bytes(path.read_bytes())

        publisher.run(candidate, postvalidate, report)
    except Exception as exc:
        report.setdefault("error", str(exc))
        if report["result"] in {"PREVALIDATING", "RECOVERY_PREFLIGHT"}:
            report.update(result="PREVALIDATION_FAILED", rollback="NOT_NEEDED_NO_PUBLICATION")
        raise
    finally:
        (work / "release-report.json").write_text(json_text(report), encoding="utf-8")
        print(json_text(report))


if __name__ == "__main__":
    main()
