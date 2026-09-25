"""Official-network fact radar. Extracted facts never mutate production candidates."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import urllib.error
from html.parser import HTMLParser

from rules import ROOT, Rule, read_json, json_text, sha256, parse_v2fly

# Partial-label wildcards must not be truncated into broader parent domains.
DOMAIN_TOKEN = re.compile(r"(?<![\w@.*-])(?:\*\.)?(?:\.)?(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}(?![\w.*-])")
FILE_SUFFIXES = {"json", "yaml", "yml", "toml", "md", "txt", "py", "js", "ts", "pem", "crt", "key", "log", "conf", "sh"}


def error_detail(exc, limit=300):
    """Stable, bounded single-line diagnostic for automation reports."""
    text = " ".join(str(exc).split())
    return (text or "(no detail)")[:limit]


class VisibleDocument(HTMLParser):
    """Drop executable/navigation markup; retain heading boundaries and visible text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer", "head", "svg"}:
            self.ignored.append(tag)
        if self.ignored:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = int(tag[1])
            self.parts.append(f"\n@@H{self.heading}@@ ")
        elif self.heading is not None:
            return
        elif tag in {"p", "li", "tr", "br", "div", "section", "article", "pre"}:
            self.parts.append("\n")
        elif tag in {"td", "th", "code"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = None
            self.parts.append("\n")
        elif self.heading is not None:
            return
        elif tag in {"p", "li", "tr", "div", "section", "article", "code", "td"}:
            self.parts.append("\n" if tag != "code" else " ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(re.sub(r"\s+", " ", data) if self.heading else data)


def visible_sections(content, names):
    parser = VisibleDocument()
    parser.feed(content)
    text = "".join(parser.parts)
    text = "\n".join(re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip())
    headings = list(re.finditer(r"^@@H([1-6])@@ (.+)$", text, re.M))
    selected, found = [], set()
    for index, heading in enumerate(headings):
        title = heading[2].replace("\u200b", "").strip()
        if title not in names:
            continue
        found.add(title)
        stop = next((other.start() for other in headings[index + 1:] if int(other[1]) <= int(heading[1])), len(text))
        selected.append(text[heading.start():stop].strip())
    if found != set(names):
        raise ValueError(f"Official document section missing: {sorted(set(names) - found)}")
    return "\n".join(sorted(set(selected)))


def validate_document(source, doc):
    """Apply the same identity/shape contract to fresh and retained official facts."""
    if (not isinstance(doc, dict) or doc.get("url") != source["url"]
            or doc.get("vendor") != source["vendor"] or doc.get("extractor") != 1
            or not isinstance(doc.get("document_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", doc["document_sha256"])):
        raise ValueError("Invalid official document identity or digest")
    rows = doc.get("rules")
    if (not isinstance(rows, list) or not rows or any(not isinstance(row, str) for row in rows)
            or len(rows) != len(set(rows))):
        raise ValueError("Invalid official document rules")
    parsed = [Rule.from_text(row) for row in rows]
    hosts = {rule.value for rule in parsed}
    if (any(rule.kind not in {"DOMAIN", "DOMAIN-SUFFIX"} for rule in parsed)
            or not set(source["required_hosts"]).issubset(hosts)
            or not source["min_hosts"] <= len(hosts) <= 512):
        raise ValueError(f"Official document shape/count guard failed: {source['id']}")
    return doc


def extract_document(source, payload):
    if source["format"] == "discovery":
        doc = json.loads(payload)
        if not isinstance(doc, dict) or doc.get("name") != "generativelanguage" or doc.get("kind") != "discovery#restDescription":
            raise ValueError("Unexpected Google Discovery document")
        urls = [doc.get(key, "") for key in ("rootUrl", "baseUrl", "mtlsRootUrl")]
        if any(not isinstance(url, str) for url in urls):
            raise ValueError("Google Discovery URL fields must be strings")
        text = "\n".join(urls)
    else:
        text = visible_sections(payload.decode("utf-8-sig"), source["sections"])
    rules = set()
    for match in DOMAIN_TOKEN.finditer(html.unescape(text)):
        token = match.group().lower()
        value = token.lstrip("*.")
        if value.rsplit(".", 1)[-1] in FILE_SUFFIXES - {"sh"}:
            continue
        rule = Rule("DOMAIN-SUFFIX" if token.startswith(("*.", ".")) else "DOMAIN", value)
        rule.validate()
        rules.add(rule.text)
    return validate_document(source, {
        "url": source["url"],
        "vendor": source["vendor"],
        "document_sha256": sha256(text.encode()),
        "rules": sorted(rules),
        "extractor": 1,
    })


def fetch_official(source, fetch):
    try:
        return fetch(source["url"]), "standard-https"
    except urllib.error.HTTPError as exc:
        if exc.code != 403 or source["url"] != "https://help.openai.com/en/articles/9247338":
            raise
        exc.close()
    try:
        from curl_cffi import requests
        chunks, size = [], 0

        def receive(chunk):
            nonlocal size
            size += len(chunk)
            if size > 4_000_000:
                raise ValueError("Oversized official document")
            chunks.append(chunk)

        response = requests.get(
            source["url"], impersonate="chrome", timeout=30,
            allow_redirects=False, content_callback=receive,
        )
        response.raise_for_status()
        if response.status_code != 200 or not size:
            raise ValueError("Unexpected official response")
        return b"".join(chunks), "browser-compatible-https"
    except Exception as exc:
        raise OSError(f"Official HTTPS fallback failed: {type(exc).__name__}: {error_detail(exc)}") from exc


def refresh_official(root, fetch):
    """Refresh each official fact source independently; retain last-valid data on failure."""
    state = read_json(root / "sources/official-state.json")
    if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("documents"), dict):
        raise ValueError("Invalid official state structure")
    updated = {"schema": 1, "documents": {}}
    report = {"sources": {}, "review_required": []}
    sources = read_json(root / "sources/official.json")["sources"]
    for source in sources:
        try:
            updated["documents"][source["id"]] = validate_document(source, state["documents"].get(source["id"]))
        except ValueError:
            pass  # A fresh response can repair it; an invalid baseline cannot be retained.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_official, source, fetch): source for source in sources}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                payload, transport = job.result()
                doc = extract_document(source, payload)
                old = updated["documents"].get(source["id"])
                facts_changed = old is None or any(
                    doc.get(key) != old.get(key) for key in ("url", "vendor", "rules")
                )
                document_changed = old is not None and doc.get("document_sha256") != old.get("document_sha256")
                # Persist endpoint facts, not harmless documentation wording churn.
                # The current document hash remains visible in this run report.
                if facts_changed:
                    updated["documents"][source["id"]] = doc
                report["sources"][source["id"]] = {
                    "status": "fresh",
                    "changed": facts_changed,
                    "document_changed": document_changed,
                    "document_sha256": doc["document_sha256"],
                    "rule_count": len(doc["rules"]),
                    "transport": transport,
                }
            except (OSError, ValueError, KeyError) as exc:
                detail = error_detail(exc)
                report["sources"][source["id"]] = {
                    "status": "retained-last-good" if source["id"] in updated["documents"] else "unavailable-no-baseline",
                    "error_type": type(exc).__name__,
                    "error_detail": detail,
                }
                report["review_required"].append({
                    "source_id": source["id"],
                    "source": source["url"],
                    "reason": "official-source-unavailable-or-parser-drift",
                    "status": report["sources"][source["id"]]["status"],
                    "error_type": type(exc).__name__,
                    "error_detail": detail,
                })
    return updated, report


def official_policy_reason(policy, rule):
    reason = policy["official_exclude_exact"].get(rule.value)
    suffixes = policy["official_exclude_suffixes"] | policy["official_shared_suffixes"]
    for suffix, why in suffixes.items():
        if rule.value == suffix or rule.value.endswith("." + suffix):
            reason = why
    return reason


def covered_by_vendor(rule, vendor, production_entries):
    """Whether the already-reviewed production rules cover this official fact."""
    for entry_vendor, tier, existing in production_entries:
        if entry_vendor != vendor or tier != "core":
            continue
        if existing == rule:
            return True
        if existing.kind == "DOMAIN-SUFFIX" and rule.kind in {"DOMAIN", "DOMAIN-SUFFIX"} and existing.matches(rule.value):
            return True
        if rule.kind == "DOMAIN" and existing.kind == "DOMAIN-REGEX" and existing.matches(rule.value):
            return True
    return False


def analyze_official(root, state, production_entries):
    """Report official gaps without granting them production authority."""
    policy = read_json(root / "sources/intake-policy.json")
    config = read_json(root / "sources/official.json")
    patches = read_json(root / "sources/patches.json")
    report = {"review_required": [], "decisions": []}
    for source in config["sources"]:
        doc = state["documents"].get(source["id"])
        if doc is None:
            continue
        if doc["url"] != source["url"] or doc["vendor"] != source["vendor"]:
            raise ValueError("Official snapshot identity mismatch")
        evidence = [(source["vendor"], "core", Rule.from_text(text)) for text in doc["rules"]
                    if not official_policy_reason(policy, Rule.from_text(text))]
        for patch in patches.get("add", []):
            if patch["vendor"] != source["vendor"] or patch["source"] != source["url"]:
                continue
            rule = Rule.from_text(patch["rule"])
            if ((patch["vendor"], patch["tier"], rule) in production_entries
                    and not covered_by_vendor(rule, patch["vendor"], evidence)):
                report["review_required"].append({
                    "source_id": source["id"], "source": source["url"], "vendor": source["vendor"],
                    "rule": rule.text, "reason": "official-patch-evidence-missing",
                    "action": "Latest valid source facts no longer cover this patch; retain reviewed authority pending verification",
                })
        for text in doc["rules"]:
            rule = Rule.from_text(text)
            reason = official_policy_reason(policy, rule)
            dropped = patches.get("drop", {}).get(source["vendor"], {})
            if text in dropped:
                report["decisions"].append({
                    "source_id": source["id"], "vendor": source["vendor"], "rule": text,
                    "action": "excluded-local-policy", "reason": dropped[text],
                })
            elif reason:
                report["decisions"].append({
                    "source_id": source["id"], "vendor": source["vendor"], "rule": text,
                    "action": "excluded-shared-or-placeholder", "reason": reason,
                })
            elif covered_by_vendor(rule, source["vendor"], production_entries):
                report["decisions"].append({
                    "source_id": source["id"], "vendor": source["vendor"], "rule": text,
                    "action": "already-covered",
                })
            else:
                report["review_required"].append({
                    "source_id": source["id"], "source": source["url"], "vendor": source["vendor"],
                    "rule": text, "reason": "official-uncovered-domain",
                    "action": "Evidence only: review product relevance and add a narrow patch only if warranted",
                })
    return report


def analyze_selected_sources(root, data, production_entries):
    """Read-only product-section radar; candidates persist by rescanning current facts."""
    watched = read_json(root / "sources/watch.json").get("primary_sections", [])
    patches = read_json(root / "sources/patches.json")
    catalog = read_json(root / "sources/catalog.json")
    vendors = {vendor["id"]: vendor for vendor in catalog["vendors"]}
    pending = []
    for watch in watched:
        vendor, source = watch["vendor"], watch["source"]
        if source not in vendors[vendor].get("select", {}):
            raise ValueError(f"Selection radar must reference a mixed selected source: {vendor}/{source}")
        wanted, seen, found = set(watch["sections"]), set(), set()
        section = None
        for line in (data / source).read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and not line.startswith("# https://"):
                section = line[2:].strip()
                if section in wanted:
                    seen.add(section)
            if section in wanted:
                for rule, attrs in parse_v2fly(line):
                    if isinstance(rule, Rule) and "@ads" not in attrs:
                        found.add((section, rule))
        for section, rule in sorted(found):
            if rule.text in patches.get("drop", {}).get(vendor, {}):
                continue
            if not covered_by_vendor(rule, vendor, production_entries):
                pending.append({"vendor": vendor, "source": f"v2fly:data/{source}",
                                "section": section, "rule": rule.text,
                                "reason": "selected-product-uncovered-domain"})
        if seen != wanted:
            pending.append({"vendor": vendor, "source": f"v2fly:data/{source}",
                            "section": ", ".join(sorted(wanted - seen)),
                            "reason": "selected-product-section-drift"})
    return pending


def main():
    from sync import fetch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-official", action="store_true")
    args = parser.parse_args()
    state, report = refresh_official(ROOT, fetch)
    if args.refresh_official:
        (ROOT / "sources/official-state.json").write_text(json_text(state), encoding="utf-8", newline="\n")
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    (work / "official-report.json").write_text(json_text(report), encoding="utf-8", newline="\n")
    print(json_text(report))


if __name__ == "__main__":
    main()
