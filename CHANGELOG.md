# Changelog

## 2026-09-21 — Permanent IPv6 runtime regression coverage

- Exercise a fixed test-only IPv6 CIDR through the existing HTTP provider and real daily routing probes in both cores, with four independent boundary expectations and separate report counts.
- Require HTTP provider recovery to restore both original routing and cache bytes; a disappeared canary alone can no longer produce a false recovery PASS for an empty provider.

## 2026-09-21 — Isolate regression fixtures from changing upstream data

- Give selection-radar tests fixed source/catalog fixtures so real pending candidates or upstream section renames remain diagnostic and cannot block unrelated production updates through test assumptions.
- Give the Voice truncation test its own verified multi-range baseline so a valid reviewed small production baseline is not mistaken for a failed safety test.

## 2026-09-21 — Routing contracts and dependency freshness

- Add independent positive/negative contracts for all 24 vendors, including same-aggregate vendor swaps and critical-entry retention. Continue to recover old releases without accepting weaker contracts for new candidates.
- Validate the domestic profile in both pinned cores and probe every Voice IP range's boundaries and adjacent addresses; preserve the existing rule bytes and product scope.
- Publish dependency upgrades only by fast-forwarding the exact tested commit when it contains current main; reject stale candidates and concurrent main changes without force pushing or creating an untested merge.
- Show each production source and official radar source's fresh/retained/unavailable state in the existing Actions summary, including explicit unknown states when evidence is absent.

## 2026-09-21 — Cloudflare runtime compatibility

- Fix a real cloud Cron failure: Workers fetch rejects `redirect: error`. Use `manual` and reject unexpected HTTP status codes, preserving the refusal to follow redirects with credentials.

## 2026-09-21 — Primary scheduling and routine dependency automation

- Use Cloudflare as the primary trigger at 00:01/06:01/12:01/18:01 China time; run GitHub cron 30 minutes later as a history-aware backup. Successful skipped backups never suppress the primary.
- Check dependencies weekly and automatically merge Dependabot groups, including major updates, only after current-commit Linux/Windows CI succeeds. Failures remain unmerged; no PR code runs in the privileged merge workflow.
- Clarify that hourly client refresh downloads published rule files and does not build rules locally.

## 2026-09-21 — Discovery and release reliability

- Add Google's reviewed `notebook.google` entry and independent positive/negative routing cases.
- Keep mixed-source product candidates visible through the existing review report, without new persistent state or automatic scope expansion.
- Reject empty semantic contracts and known shared/public boundaries; retain verified Voice IPs when fetched coverage changes abruptly.
- Preserve stable/LKG for evidence-only updates and validate remote bytes against the actual published revision.
- Let optional official-document transport installation degrade without stopping production updates; group monthly Actions/Python dependency PRs.
- Reduce example client refresh to one hour; provide a small Cloudflare cron backup using existing GitHub run history, with no new alerts or database.

## 2026-09-18 — Dedicated-source automation

- Removed the duplicate `approvals.json` layer: `catalog.sources`, `catalog.select` and `patches` are now the production authority model.
- Direct ordinary rules from a vendor-dedicated V2Fly source can absorb new domains automatically; transitive includes do not inherit that authority.
- Whole shared-platform roots, unsupported broad matches and unreviewed regex adapters remain fail-closed; local drops/select removals cannot be resurrected by retention.
- Existing generated rule bytes remain unchanged; this changes how future upstream additions are admitted, not the current profiles.

## 2026-09-16 — Small, high-confidence architecture

- Reduced the maintained products to explicit profiles: ai-daily 5 overseas vendors + OpenAI Voice, ai-core 14 overseas vendors, and ai-cn 10 domestic vendors.
- Removed long-tail/default compatibility products and narrowed Google AI to Gemini / AI Studio / NotebookLM scope.
- Made pinned v2fly the only general-domain production feed; official network docs and weekly Sukka Source are read-only gap radars.
- Changed select-mode v2fly consumption to top-level explicit rules only; source-mode retains recursive include semantics.
- Replaced duplicated protected-host state with small independent semantic contracts and exact aggregate-profile composition checks.
- Freeze deletion aging on retained/failed upstream observations; select structure drift quarantines the affected vendor instead of silently deleting.
- Verify/recover stable before new source fetch, keep main as candidate-only, and roll back stable without rewriting main.
- Keep transient source health in run reports instead of production locks, and retain AGPL without another license migration.

## 2026-09-15 — Official OpenAI CDN coverage

- Added only the exact cdn.openaimerge.com hostname from OpenAI's official network allowlist; no wildcard or whole-parent-domain expansion.
- Reproduced the missing match before the fix; expanded to 63 regression tests and 40 routing probes per Mihomo profile.
- Corrected voice guidance: UDP is preferred, with TCP fallback documented by OpenAI.

## 2026-09-15 — Personal-use review and simpler subscriptions

- Reduced the main entry table to daily recommended, overseas domains only and domestic AI, each with a short selection guide.
- Generated a separate collection/vendor/optional subscription index; all existing raw URLs remain stable, without compatibility mirrors.
- Grouped rules by vendor and precise source evidence, preserving attribution when deduplicating; annotated retained upstream removals.
- Added scoped copyright and full MIT notices to standalone downloads, documented unknown/AGPL/official-data limits and gated upstream license changes.
- Report workflow failures through the existing deduplicated issue channel; missing reports cannot silently close an exception.
- Pinned Node 24 GitHub Actions, clarified actual update inputs and inactive-schedule limits; fixed UTF-8 rule reading on Windows.
- Expanded regression coverage to 62 tests; active routing sets remain unchanged.

## 2026-09-15 — Daily bundle and unattended updates

- Added ai-daily: 19 overseas vendor groups plus official OpenAI voice IPs, with one-subscription examples.
- Safe changes continue when unapproved additions are quarantined; critical entries remain protected.
- Automatic 14-day / 3-observation-day retirement for noncritical upstream removals; redundant removals need no waiting.
- Retry transient downloads and retain verified voice IPs during official-source outages.
- Semantically triage secondary source changes and maintain deduplicated exception issues only when needed.
- Expanded to 51 tests; validate daily and split profiles, proxy-listener readiness and fragmented HTTP status lines in the isolated Mihomo harness.

## 2026-09-15 — Initial release

- 26 vendor/service groups, Surge RULE-SET and FlClash/Mihomo classical YAML.
- Separate core, domestic classification, shared compatibility and OpenAI voice IP bundles.
- Immutable v2fly snapshot, provenance, output hashes and explicit source-scope approval.
- Reviewed Cursor/Google/Runway/Suno patches; no whole-cloud ASN or blanket process routing.
- Explicitly documented Surge approximation for one OpenAI hostname regex.
- Six-hour guarded sync and daily review-only secondary-source monitoring.
- Automated tests and isolated Mihomo engine verification; client functionality testing remains explicitly unclaimed.
