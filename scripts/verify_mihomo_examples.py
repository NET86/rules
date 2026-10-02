#!/usr/bin/env python3
"""Load shipped YAML examples with isolated local providers and virtual outlets."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

from rules import ROOT, json_text, read_json
from verify_rules import load_contracts
from verify_mihomo import (CaptureProxy, NonMatchingProxy, QuietFileHandler,
                           free_port, probe, providers_ready, proxy_ready, voice_probe_cases)


class OpenAIProxy(CaptureProxy):
    response = b"HTTP/1.1 205 OpenAI Outlet\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


class ExampleRejected(RuntimeError):
    """Only core parse rejection or an evidenced wrong route rejects a negative."""


def mutate(text, case):
    if case == "behavior-typo":
        return text.replace("behavior: classical", "behavior: classcial", 1)
    if case == "missing-provider":
        return re.sub(r"(  - RULE-SET,)[^,\n]+", r"\1nonexistent-provider", text, count=1)
    if case == "wrong-order":
        lines = text.splitlines()
        indices = [i for i, line in enumerate(lines) if line.startswith("  - RULE-SET,")]
        if len(indices) == 1:
            lines.insert(indices[0], "  - MATCH,LOCAL-NONMATCH")
        else:
            first, second = indices[:2]
            lines[first], lines[second] = lines[second], lines[first]
        return "\n".join(lines) + "\n"
    raise ValueError(f"Unknown negative case: {case}")


def isolated_config(text, manifest, server_port, port, controller, outlets):
    # The core parses the original YAML: never reconstruct providers or rules,
    # which would mask bad properties or the user's actual rule order.
    def local_url(match):
        bundle = match[1]
        if bundle not in manifest["bundles"]:
            raise ValueError("Example URL refers to an unpublished bundle")
        return f"    url: http://127.0.0.1:{server_port}/{bundle}.yaml"

    text, count = re.subn(
        r"^    url: https://raw\.githubusercontent\.com/NET86/rules/stable/rules/mihomo/([a-z0-9-]+)\.yaml$",
        local_url, text, flags=re.MULTILINE)
    if not count or re.search(r"https://|http://(?!127\.0\.0\.1:)", text):
        raise ValueError("Example URLs must use the public stable interface")
    # Add a distinguishable virtual node to OpenAI while retaining its AI entry.
    # AI's include-all exposes the other injected nodes without rewriting it.
    text = text.replace("proxies: [AI]", "proxies: [AI, LOCAL-OPENAI]")
    # Both snippets end in their rules list. Add the documented fallback only.
    text = text.rstrip() + "\n  - MATCH,LOCAL-NONMATCH\n"
    runtime = {
        "port": port, "bind-address": "127.0.0.1", "allow-lan": False,
        "mode": "rule", "log-level": "info", "ipv6": True, "find-process-mode": "off",
        "external-controller": f"127.0.0.1:{controller}", "secret": "isolated-local-test",
        "dns": {"enable": False}, "tun": {"enable": False},
        "profile": {"store-selected": False, "store-fake-ip": False},
        "proxies": [{"name": name, "type": "http", "server": "127.0.0.1", "port": outlet}
                    for name, outlet in outlets.items()],
    }
    # JSON values are valid YAML flow values; no extra YAML dependency.
    return text + "\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in runtime.items()) + "\n"


def routing_cases(root, manifest, profile, split):
    contracts = load_contracts(root, manifest)
    contract = contracts["profiles"][profile]
    openai = contracts["vendors"]["openai"]["must_match"]
    cases = {}
    for host in contract["must_match"]:
        cases[host] = b"205" if split and host in openai else b"204"
    if split:
        cases.update({host: b"205" for host in openai})
    for host in contract["must_not_match"]:
        cases[host] = b"418"
    for host, matches in voice_probe_cases(root, manifest, True):
        cases[host] = (b"205" if split else b"204") if matches else b"418"
    return cases


def verify_example(binary, engine_label, base, config, expected_providers, cases, log_path):
    base.mkdir()
    port, controller = free_port(), free_port()
    config_path = base / "config.yaml"
    config_path.write_text(config(port, controller), encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    command = [binary, "-d", str(base), "-f", str(config_path)]
    parsed = subprocess.run(command + ["-t"], capture_output=True, text=True, timeout=45, creationflags=flags)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n{base.name}: parse\n" + parsed.stdout + parsed.stderr)
    if parsed.returncode:
        raise ExampleRejected("core-parse-rejection")
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def request(path, method="GET", body=None):
                req = urllib.request.Request(f"http://127.0.0.1:{controller}{path}", method=method,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={"Authorization": "Bearer isolated-local-test", "Content-Type": "application/json"})
                with opener.open(req, timeout=3) as response:
                    data = response.read()
                    return json.loads(data) if data else None

            loaded = None
            listener_started = False
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError("Example engine exited before readiness")
                try:
                    loaded = request("/providers/rules")["providers"]
                    if engine_label == "flclash-core" and not listener_started:
                        request("/configs", "PATCH", {"port": port, "allow-lan": False,
                            "bind-address": "127.0.0.1", "lan-allowed-ips": ["127.0.0.1/32"],
                            "lan-disallowed-ips": [], "tun": {"enable": False}})
                        listener_started = True
                    if providers_ready(loaded, expected_providers) and proxy_ready(port):
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            if not providers_ready(loaded, expected_providers) or not proxy_ready(port):
                raise RuntimeError("Example providers or isolated listener not ready")
            for name, count in expected_providers.items():
                if loaded[name]["ruleCount"] != count:
                    raise RuntimeError(f"Example provider count mismatch: {name}")
            # Follow the documented node-selection action through the controller.
            # Group contents stay intact: include-all must expose injected nodes.
            request("/proxies/AI", "PUT", {"name": "LOCAL-CAPTURE"})
            if any(status == b"205" for status in cases.values()):
                request("/proxies/OpenAI", "PUT", {"name": "LOCAL-OPENAI"})
            for host, expected in cases.items():
                if not probe(port, host, expected_status=expected):
                    raise ExampleRejected(f"routing-mismatch:{host}:expected-{expected.decode()}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / ".work/bin" / ("mihomo.exe" if os.name == "nt" else "mihomo"))
    parser.add_argument("--engine-label", default="mihomo")
    args = parser.parse_args()
    manifest = read_json(ROOT / "rules/manifest.json")
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    reports = []
    with ExitStack() as stack:
        base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="mihomo-examples-", dir=work)))
        directory = base / "providers"
        directory.mkdir()
        for name, targets in manifest["bundles"].items():
            shutil.copyfile(ROOT / targets["mihomo"]["path"], directory / f"{name}.yaml")
        outlets = {}
        for name, handler in (("LOCAL-CAPTURE", CaptureProxy), ("LOCAL-OPENAI", OpenAIProxy),
                              ("LOCAL-NONMATCH", NonMatchingProxy)):
            server = stack.enter_context(socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler))
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            outlets[name] = server.server_address[1]
        server = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0),
            functools.partial(QuietFileHandler, directory=str(directory))))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown)
        for filename, profile, bundles in (
                ("flclash-daily.yaml", "ai-daily", {"net86-ai-daily": "ai-daily"}),
                ("flclash-mihomo.yaml", "ai-core", {"net86-openai": "openai",
                    "net86-ai-core": "ai-core", "net86-openai-voice": "openai-voice-ip"})):
            text = (ROOT / "examples" / filename).read_text(encoding="utf-8")
            cases = routing_cases(ROOT, manifest, profile, profile == "ai-core")
            counts = {name: manifest["bundles"][bundle]["mihomo"]["count"] for name, bundle in bundles.items()}
            report = {"example": f"examples/{filename}", "routing_case_count": len(cases), "negative_cases": {}}
            for case in ("baseline", "behavior-typo", "missing-provider", "wrong-order"):
                candidate = text if case == "baseline" else mutate(text, case)
                config = lambda port, controller: isolated_config(candidate, manifest, server.server_port, port, controller, outlets)
                try:
                    verify_example(str(args.binary.resolve()), args.engine_label, base / f"{filename}-{case}",
                                   config, counts, cases, work / "mihomo-examples.log")
                except ExampleRejected as error:
                    if case == "baseline":
                        raise
                    report["negative_cases"][case] = str(error)
                else:
                    if case != "baseline":
                        raise RuntimeError(f"Broken example passed: {filename} ({case})")
                    report["result"] = "PASS"
            reports.append(report)
            print(f"PASS {filename}: {len(cases)} routing probes; all three broken variants rejected")
    (work / f"{args.engine_label}-examples-validation.json").write_text(json_text({
        "engine_label": args.engine_label, "examples": reports, "result": "PASS",
        "scope": "Shipped YAML, local HTTP providers and selected virtual outlets; no client UI or remote AI calls"}), encoding="utf-8")


if __name__ == "__main__":
    main()
