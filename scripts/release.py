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
SUMMARY_LIMIT = 10
REVIEW_REASON_LABELS = {
    "source-not-authorized-by-catalog": "来源未被 catalog 授权，已隔离",
    "unsupported-tier": "规则层级不受当前生产模型支持，已隔离",
    "unsupported-or-broad-matching": "不支持或过宽的匹配，已隔离",
    "shared-platform-forbidden-in-core": "共享基础设施不允许进入 core，已隔离",
    "unreviewed-surge-regex-adapter": "新正则 / Surge 适配尚未审核，已隔离",
    "protected-upstream-removal": "关键规则疑似被上游删除，当前继续保留",
    "selected-upstream-domain-disappeared-or-moved": "选定上游目标消失或结构漂移，需要复核",
    "official-uncovered-domain": "官方资料发现未覆盖域名，需要复核",
    "official-patch-evidence-missing": "最近有效官方资料不再覆盖人工补丁，保留授权并等待复核",
    "official-source-unavailable-or-parser-drift": "官方来源不可用或解析结构变化",
    "official-voice-fetch-unavailable": "OpenAI 语音官方源不可用，沿用上一有效版本",
    "official-voice-suspicious-change": "OpenAI 语音范围大幅变化，沿用上一有效版本等待核验",
    "selected-product-uncovered-domain": "已维护产品所在的混合来源发现未覆盖规则，需要核验",
    "selected-product-section-drift": "混合来源产品区段变化，需要检查发现范围",
    "v2fly-unavailable-or-license-changed": "V2Fly 不可用或许可证变化，沿用上一有效快照",
    "workflow-failed": "工作流失败",
}


def manifest_changes(before, after):
    def rows(manifest):
        return {
            (row["vendor"], row["rule"]): {
                "tier": row["tier"],
                "sources": tuple(row.get("sources", [])),
            }
            for row in manifest.get("provenance", [])
        }

    old, new = rows(before), rows(after)
    added = [
        {"vendor": vendor, "rule": rule, **new[(vendor, rule)]}
        for vendor, rule in sorted(new.keys() - old.keys())
    ]
    removed = [
        {"vendor": vendor, "rule": rule, **old[(vendor, rule)]}
        for vendor, rule in sorted(old.keys() - new.keys())
    ]
    changed = []
    for vendor, rule in sorted(old.keys() & new.keys()):
        if old[(vendor, rule)] != new[(vendor, rule)]:
            changed.append({
                "vendor": vendor,
                "rule": rule,
                "before": old[(vendor, rule)],
                "after": new[(vendor, rule)],
            })
    return added, changed, removed


def format_review_item(row):
    subject = row.get("vendor") or row.get("source_id") or "system"
    parts = [f"`{subject}`"]
    rule = row.get("rule") or row.get("value")
    if rule:
        parts.append(f"`{rule}`")
    if row.get("tier"):
        parts.append(str(row["tier"]))
    reason = row.get("reason", "unknown")
    text = " · ".join(parts) + " — " + REVIEW_REASON_LABELS.get(reason, reason)
    if row.get("error_type"):
        text += f"（{row['error_type']}）"
    return text


def render_actions_summary(before, after, sync_report, release_report, limit=SUMMARY_LIMIT):
    comparable = before is not None and after is not None
    before, after = before or {}, after or {}
    added, changed, removed = manifest_changes(before, after)
    old_bundles, new_bundles = before.get("bundles", {}), after.get("bundles", {})
    bundle_changes = [name for name in sorted(old_bundles.keys() | new_bundles.keys())
                      if old_bundles.get(name) != new_bundles.get(name)] if comparable else []
    lines = ["## 规则同步摘要", "", "### 发布结果",
             f"- 结果：**{release_report.get('result', '未开始或未生成报告')}**"]
    if release_report.get("stable_noop") == "UNCHANGED_RELEASE_CONTENT":
        lines.append("- stable：订阅产物和产品契约无变化，未轮换（`UNCHANGED_RELEASE_CONTENT`）")
    elif release_report.get("result") == "PASS" and release_report.get("stable_remote_validation") == "PASS":
        lines.append("- stable：已更新并通过远端验证")
    else:
        lines.append("- 未确认新的稳定版本发布成功；以回读和恢复结果为准。")
    stable_label = "稳定提交" if release_report.get("result") == "PASS" else "本次目标 stable"
    for key, label in (("candidate", "候选提交"), ("stable_revision", stable_label),
                       ("stable_after_failure", "失败后 stable（观测值）"),
                       ("rollback", "失败恢复"), ("rollback_remote_validation", "恢复回读")):
        if release_report.get(key):
            lines.append(f"- {label}：`{release_report[key]}`")
    for key, label in (("error", "原因"), ("rollback_error", "恢复异常")):
        if release_report.get(key):
            detail = " ".join(str(release_report[key]).split())[:300].replace("`", "'")
            lines.append(f"- {label}：`{detail}`")
    lines.extend(["", "变化口径：候选相对上次 stable；未通过发布的候选变化不代表已生效。", "", "### 规则变化"])
    if not comparable:
        lines.append("- 对比数据不可用，未判断规则变化。")
    elif not (added or changed or removed or bundle_changes):
        lines.append("- 无变化")
    else:
        def append_group(title, rows, formatter):
            if not rows:
                return
            lines.extend(["", f"#### {title}（{len(rows)}）"])
            for row in rows[:limit]:
                lines.append("- " + formatter(row))
            extra = len(rows) - limit
            if extra > 0:
                lines.append(f"- 另有 **{extra}** 条，详见完整提交差异。")

        append_group(
            "新增", added,
            lambda row: f"`{row['vendor']}` · `{row['rule']}` · {row['tier']}",
        )

        def changed_text(row):
            details = []
            if row["before"]["tier"] != row["after"]["tier"]:
                details.append(f"层级 {row['before']['tier']} → {row['after']['tier']}")
            if row["before"]["sources"] != row["after"]["sources"]:
                details.append("来源变化")
            return f"`{row['vendor']}` · `{row['rule']}` · " + "；".join(details)

        append_group("变化", changed, changed_text)
        append_group(
            "删除", removed,
            lambda row: f"`{row['vendor']}` · `{row['rule']}` · {row['tier']}",
        )

    if bundle_changes:
        lines.extend(["", f"#### 订阅文件变化（{len(bundle_changes)}）"])
        for name in bundle_changes[:limit]:
            old_count = old_bundles.get(name, {}).get("mihomo", {}).get("count", "无")
            new_count = new_bundles.get(name, {}).get("mihomo", {}).get("count", "无")
            lines.append(f"- `{name}`：{old_count} → {new_count} 条；订阅文件记录变化")
        if len(bundle_changes) > limit:
            lines.append(f"- 另有 **{len(bundle_changes) - limit}** 个规则集，详见完整提交差异。")

    review_required = sync_report.get("review_required", [])
    lines.extend([
        "",
        "### 同步状态",
        f"- 待审核 / 异常：**{len(review_required) if 'review_required' in sync_report else '未知（未生成报告）'}**",
        f"- 隔离：**{sync_report.get('quarantined_count', '未知')}**",
        f"- 保留观察：**{sync_report.get('retained_count', '未知')}**",
    ])
    health = sync_report.get("source_health", {})
    labels = {
        "fresh": "抓取成功",
        "reviewed-local-input": "采用维护者指定的本地输入",
        "retained-last-good": "沿用最近有效版本（本次来源更新未通过）",
        "retained-suspicious-change": "沿用旧版（变化异常）",
        "unavailable-no-baseline": "不可用（无有效基线）",
    }
    lines.extend(["", "### 来源状态"])
    for source, label in (("v2fly", "V2Fly"), ("openai_voice", "OpenAI 语音")):
        lines.append(f"- {label}：{labels.get(health.get(source), '未知（未提供状态）')}")
    facts = health.get("official_facts", {})
    if facts:
        fresh = sum(status.get("status") == "fresh" for status in facts.values())
        lines.append(f"- 官方资料：{fresh} / {len(facts)} 份抓取成功；完整明细见 sync-report.json。")
        for source, status in sorted(facts.items()):
            if status.get("status") != "fresh":
                lines.append(f"- 官方资料 `{source}`：{labels.get(status.get('status'), '未知（未提供状态）')}")
    else:
        lines.append("- 官方资料：未知（未提供状态）")
    if review_required:
        lines.extend(["", f"### 待审核 / 异常明细（{len(review_required)}）"])
        for row in review_required[:limit]:
            lines.append("- " + format_review_item(row))
        extra = len(review_required) - limit
        if extra > 0:
            lines.append(f"- 另有 **{extra}** 条，详见异常 Issue 或 sync-report.json。")

    return "\n".join(lines) + "\n"


def render_workflow_summary(root, channel, job_status):
    """Read this job's evidence only; never publish, recover or fetch remote data."""
    notes = []

    def load(relative):
        path = root / relative
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected report object")
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            notes.append(f"- `{relative}`：报告无效，未将其判为成功。")
            return None

    titles = {"sync": "规则同步", "ci": "规则校验", "sources": "来源补缺", "dependencies": "依赖升级"}
    lines = [f"## {titles[channel]} · 作业结果：{job_status}", "",
             "状态截至摘要步骤，最终状态以 Actions 为准；发布和合并结果单独报告。", ""]
    if channel == "sync":
        report = load(".work/release-report.json") or {}
        source = load(".work/sync-report.json") or {}
        after = load("rules/manifest.json")
        before = None
        revision = report.get("previous_stable", "")
        if isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40}", revision):
            try:
                before = json.loads(Publisher(root).git("show", f"{revision}:rules/manifest.json"))
                if not isinstance(before, dict):
                    raise ValueError("Invalid previous manifest")
            except (OSError, ValueError, subprocess.SubprocessError):
                before = None
                notes.append("- 上次 stable 的对比数据不可用；未用 main 冒充发布基线。")
        lines.append(render_actions_summary(before, after, source, report))
        recovery = load(".work/recovery-report.json") or {}
        lines.append(f"恢复预检：`{recovery.get('stable_preflight', recovery.get('result', '未生成报告'))}`。")
    elif channel == "ci":
        portable = load(".work/portable-validation.json") or {}
        lines += ["本作业只校验，未执行生产发布。", "",
                  f"可移植校验：`{portable.get('result', '未完成或未生成报告')}`；"
                  f"产物 {portable.get('artifact_count', '未知')}，语义用例 {portable.get('semantic_case_count', '未知')}。", "",
                  "| 内核 / 配置 | 报告 | 路由用例 |", "| --- | --- | --- |"]
        engines = ("mihomo",) if os.environ.get("RUNNER_OS") == "Windows" else ("mihomo", "flclash-core")
        for engine in engines:
            for profile in ("ai-daily", "split", "ai-cn"):
                report = load(f".work/{engine}-validation-{profile}.json") or {}
                lines.append(f"| {engine} / {profile} | {report.get('result', '未完成')} | {report.get('routing_case_count', '未知')} |")
        lines += ["", "未执行的检查不计为通过；原生 Surge、客户端界面和真实 AI 账号连接不在此验收范围。"]
    elif channel == "sources":
        from audit_sources import render_actions_summary as audit_summary
        report = load(".work/source-audit.json")
        lines.append(audit_summary(report) if report and isinstance(report.get("review_required"), list)
                     else "补缺扫描未完成或未生成有效报告，不能判断为零缺口。")
        lines.append("本作业只读，不修改生产规则。")
    else:
        report = load(".work/dependency-report.json")
        lines.append("只允许精确测试提交快进 main，未执行 stable 发布。")
        if report is None:
            lines.append("未生成完整合并报告；发生失败时以日志和远端引用为准。")
        else:
            lines.extend(report.get("decisions", []) or ["没有符合条件的打开 PR，未执行合并。"])
    if notes:
        lines += ["", "### 证据限制", *notes]
    lines += ["", "完整证据见本次运行的日志和 artifact；缺失报告不等于检查通过。"]
    return "\n".join(lines) + "\n"


def write_workflow_summary(channel, job_status):
    try:
        text = render_workflow_summary(ROOT, channel, job_status)
    except Exception as exc:
        text = f"## 作业结果：{job_status}\n\n摘要生成失败：`{type(exc).__name__}`；未据此判断发布结果，请查看原始日志。\n"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"))
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            print(f"WARNING: summary write failed ({type(exc).__name__}); original job outcome is unchanged", file=sys.stderr)


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
        """Keep evidence-only snapshot/observation changes on main."""
        fields = ("schema", "bundles", "profiles", "profile_features", "semantic_contract",
                  "conversion_warnings", "license", "formats")
        def surface(revision):
            manifest = json.loads(self.git("show", f"{revision}:rules/manifest.json"))
            return {field: manifest[field] for field in fields}
        return surface(candidate) == surface(stable)

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
            validate_published(candidate, "candidate", candidate)
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
                report["stable_noop"] = "UNCHANGED_RELEASE_CONTENT"
            report["stable_revision"] = promoted
            validate_published("stable", "stable", promoted)
            self.require_refs({"main": candidate, "stable": promoted})
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
                        validate_published("stable", "rollback", old_stable)
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
    parser.add_argument("--summary-only", choices=["sync", "ci", "sources", "dependencies"], help="Read-only final Actions summary; never publishes")
    parser.add_argument("--job-status", choices=["success", "failure", "cancelled", "unknown"], default="unknown")
    args = parser.parse_args()
    if args.summary_only:
        write_workflow_summary(args.summary_only, args.job_status)
        return
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
        for profile in ("ai-daily", "split", "ai-cn"):
            runtime_gate(ROOT, binaries, profile)
        publisher.git("add", "--", *AUTO_PATHS)
        if publisher.git("diff", "--cached", "--name-only"):
            publisher.git("commit", "-m", "chore: sync verified production rules")
        if publisher.git("status", "--porcelain"):
            raise ValueError("Unexpected uncommitted changes outside automatic publication scope")
        candidate = publisher.git("rev-parse", "HEAD")
        def postvalidate(revision, label, expected_revision):
            with tempfile.TemporaryDirectory(prefix="published-", dir=work) as td:
                target = Path(td)
                manifest = json.loads(publisher.git("show", f"{expected_revision}:rules/manifest.json"))
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
        name = "recovery-report.json" if args.recover_only else "release-report.json"
        (work / name).write_text(json_text(report), encoding="utf-8")
        print(json_text(report))


if __name__ == "__main__":
    main()
