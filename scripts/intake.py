"""Official-network fact radar. Extracted facts never mutate production candidates."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import urllib.error
from html.parser import HTMLParser

from rules import ROOT, Rule, read_json, json_text, sha256

DOMAIN_TOKEN = re.compile(r"(?<![\w@.-])(?:\*\.)*(?:\.)?(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}(?![\w.-])")
FILE_SUFFIXES = {"json", "yaml", "yml", "toml", "md", "txt", "py", "js", "ts", "pem", "crt", "key", "log", "conf", "sh"}


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


def extract_document(source, payload):
    if source["format"] == "discovery":
        doc = json.loads(payload)
        if doc.get("name") != "generativelanguage" or doc.get("kind") != "discovery#restDescription":
            raise ValueError("Unexpected Google Discovery document")
        text = "\n".join(str(doc.get(key, "")) for key in ("rootUrl", "baseUrl", "mtlsRootUrl"))
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
    hosts = {Rule.from_text(rule).value for rule in rules}
    if not set(source["required_hosts"]).issubset(hosts) or not source["min_hosts"] <= len(hosts) <= 512:
        raise ValueError(f"Official document shape/count guard failed: {source['id']}")
    return {
        "url": source["url"],
        "vendor": source["vendor"],
        "document_sha256": sha256(text.encode()),
        "rules": sorted(rules),
        "extractor": 1,
    }


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
        raise OSError(f"Official HTTPS fallback failed: {type(exc).__name__}") from exc


def refresh_official(root, fetch):
    """Refresh each official fact source independently; retain last-valid data on failure."""
    state = read_json(root / "sources/official-state.json")
    updated = {"schema": 1, "documents": dict(state["documents"])}
    report = {"sources": {}, "review_required": []}
    sources = read_json(root / "sources/official.json")["sources"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_official, source, fetch): source for source in sources}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                payload, transport = job.result()
                doc = extract_document(source, payload)
                old = state["documents"].get(source["id"])
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
                report["sources"][source["id"]] = {
                    "status": "retained-last-good" if source["id"] in updated["documents"] else "unavailable-no-baseline",
                    "error_type": type(exc).__name__,
                }
                report["review_required"].append({
                    "source_id": source["id"],
                    "source": source["url"],
                    "reason": "official-source-unavailable-or-parser-drift",
                    "error_type": type(exc).__name__,
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
    report = {"review_required": [], "decisions": []}
    for source in config["sources"]:
        doc = state["documents"].get(source["id"])
        if doc is None:
            continue
        if doc["url"] != source["url"] or doc["vendor"] != source["vendor"]:
            raise ValueError("Official snapshot identity mismatch")
        for text in doc["rules"]:
            rule = Rule.from_text(text)
            reason = official_policy_reason(policy, rule)
            if reason:
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
