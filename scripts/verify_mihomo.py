#!/usr/bin/env python3
"""Isolated real-engine parse/load/routing tests. No system proxy, TUN or remote AI calls."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from rules import ROOT, Rule, read_json, json_text
from verify_rules import load_contracts


class CaptureProxy(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        def headers():
            buffer = b""
            while b"\r\n\r\n" not in buffer and len(buffer) < 32768:
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                buffer += chunk
            return buffer
        data = headers()
        if data.startswith(b"CONNECT "):
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            data = headers()
        if data.startswith(b"GET "):
            self.request.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe(port, host):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=4) as sock:
            sock.sendall(f"GET http://{host}/ai-rules-local-test HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            response = b""
            # TCP does not preserve response/status-line message boundaries.
            while b"\r\n" not in response and len(response) < 1024:
                chunk = sock.recv(1024 - len(response))
                if not chunk:
                    break
                response += chunk
        return b" 204 " in response.split(b"\r\n", 1)[0]
    except (ConnectionError, TimeoutError, OSError):
        return False


def proxy_ready(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def providers_ready(loaded, names):
    """Treat transient missing/null provider state as not-ready, never as a harness crash."""
    if not isinstance(loaded, dict):
        return False
    for name in names:
        provider = loaded.get(name)
        if not isinstance(provider, dict) or provider.get("ruleCount", 0) <= 0:
            return False
    return True


class QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    unavailable = set()

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in self.unavailable:
            self.send_error(503, "Intentional isolated test outage")
            return
        super().do_GET()


def verify_http_refresh(opener, controller, port, directory, name):
    path = directory / f"{name}.yaml"
    original = path.read_bytes()
    canary = "ai-rules-refresh-canary.invalid"
    url = f"http://127.0.0.1:{controller}/providers/rules/{name}"
    headers = {"Authorization": "Bearer isolated-local-test"}

    def refresh(allow_failure=False):
        request = urllib.request.Request(url, method="PUT", headers=headers)
        try:
            with opener.open(request, timeout=10) as response:
                if response.status not in {200, 204}:
                    raise RuntimeError("Unexpected provider update status")
        except urllib.error.HTTPError:
            if not allow_failure:
                raise

    try:
        path.write_bytes(original + f'  - "DOMAIN,{canary}"\n'.encode())
        refresh()
        if not probe(port, canary):
            raise RuntimeError("HTTP provider failed to activate a valid update")
        cached = directory.parent / "cache" / f"{name}.yaml"
        known_good = cached.read_bytes()
        QuietFileHandler.unavailable.add(f"/{name}.yaml")
        refresh(allow_failure=True)
        if not probe(port, canary) or cached.read_bytes() != known_good:
            raise RuntimeError("HTTP outage replaced last-good active rules or cache")
        QuietFileHandler.unavailable.clear()
        path.write_bytes(b"payload: [unterminated\n")
        refresh(allow_failure=True)
        malformed_retained = probe(port, canary) and cached.read_bytes() == known_good
        # Some core versions accept malformed YAML as an empty provider. Record
        # that limitation honestly; our strict pre-publication gate rejects it.
        path.write_bytes(original)
        refresh()
        if probe(port, canary):
            raise RuntimeError("HTTP provider recovery failed to remove the canary")
    finally:
        QuietFileHandler.unavailable.clear()
        path.write_bytes(original)
    return {"valid_update": "PASS", "http_outage_retains_last_good": "PASS",
            "malformed_update_retains_last_good": malformed_retained,
            "malformed_content_protection": "REQUIRES_STRICT_SERVER_GATE" if not malformed_retained else "NATIVE_AND_SERVER_GATE",
            "recovery": "PASS"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / ".work/bin" / ("mihomo.exe" if os.name == "nt" else "mihomo"))
    parser.add_argument("--profile", choices=["ai-daily", "split"], default="ai-daily")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--engine-label", default="mihomo")
    args = parser.parse_args()
    root = args.root.resolve()
    binary = str(args.binary.resolve())
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    version = subprocess.check_output([binary, "-v"], text=True, creationflags=flags).strip()
    manifest = read_json(root / "rules/manifest.json")
    work = root / ".work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mihomo-test-", dir=work) as td, socketserver.ThreadingTCPServer(("127.0.0.1", 0), CaptureProxy) as capture:
        capture.daemon_threads = True
        thread = threading.Thread(target=capture.serve_forever, daemon=True)
        thread.start()
        base = Path(td)
        (base / "providers").mkdir()
        providers = {}
        for name, targets in manifest["bundles"].items():
            shutil.copyfile(root / targets["mihomo"]["path"], base / "providers" / f"{name}.yaml")
            providers[name] = {"type": "http", "behavior": "classical", "format": "yaml", "path": f"./cache/{name}.yaml", "interval": 3600, "url": ""}
        handler = functools.partial(QuietFileHandler, directory=str(base / "providers"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        for name in providers:
            providers[name]["url"] = f"http://127.0.0.1:{server.server_port}/{name}.yaml"
        port, controller = free_port(), free_port()
        selected = ["ai-daily"] if args.profile == "ai-daily" else ["ai-core", "openai-voice-ip"]
        config = {
            "mixed-port": port, "bind-address": "127.0.0.1", "allow-lan": False,
            "mode": "rule", "log-level": "info", "ipv6": False, "find-process-mode": "off",
            "external-controller": f"127.0.0.1:{controller}", "secret": "isolated-local-test",
            "dns": {"enable": False}, "tun": {"enable": False},
            "profile": {"store-selected": False, "store-fake-ip": False},
            "proxies": [{"name": "LOCAL-CAPTURE", "type": "http", "server": "127.0.0.1", "port": capture.server_address[1]}],
            "rule-providers": providers,
            "rules": ["IP-CIDR,127.0.0.1/32,DIRECT,no-resolve"] + [f"RULE-SET,{name},LOCAL-CAPTURE,no-resolve" for name in selected] + [f"RULE-SET,{name},REJECT" for name in providers if name not in selected] + ["MATCH,REJECT"]
        }
        config_path = base / "config.json"
        config_path.write_text(json_text(config), encoding="utf-8")
        command = [binary, "-d", str(base), "-f", str(config_path)]
        parsed = subprocess.run(command + ["-t"], capture_output=True, text=True, timeout=45, creationflags=flags)
        if parsed.returncode:
            raise RuntimeError(parsed.stdout + parsed.stderr)
        (work / "mihomo-parse.log").write_text(parsed.stdout + parsed.stderr, encoding="utf-8")
        with (work / "mihomo-runtime.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                loaded = None
                embedded_listener_started = False
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Mihomo exited; see .work/mihomo-runtime.log")
                    try:
                        request = urllib.request.Request(f"http://127.0.0.1:{controller}/providers/rules", headers={"Authorization": "Bearer isolated-local-test"})
                        with opener.open(request, timeout=1) as response:
                            loaded = json.load(response)["providers"]
                        if args.engine_label == "flclash-core" and not embedded_listener_started:
                            # FlClash deliberately disables ApplyConfig's listener
                            # startup; its app owns lifecycle. Use the unmodified
                            # fork's public controller to open ONLY this test port.
                            request = urllib.request.Request(f"http://127.0.0.1:{controller}/configs",
                                method="PATCH", data=json.dumps({"mixed-port": port, "allow-lan": False,
                                "bind-address": "127.0.0.1", "lan-allowed-ips": ["127.0.0.1/32"],
                                "lan-disallowed-ips": [], "tun": {"enable": False}}).encode(),
                                headers={"Authorization": "Bearer isolated-local-test", "Content-Type": "application/json"})
                            with opener.open(request, timeout=3) as response:
                                if response.status not in {200, 204}:
                                    raise RuntimeError("Embedded core listener setup failed")
                            embedded_listener_started = True
                        if providers_ready(loaded, providers) and proxy_ready(port):
                            break
                    except OSError:
                        pass
                    time.sleep(0.1)
                if not providers_ready(loaded, providers) or not proxy_ready(port):
                    raise RuntimeError(f"Providers not fully loaded: {loaded}")
                for name, target in manifest["bundles"].items():
                    if loaded[name]["ruleCount"] != target["mihomo"]["count"]:
                        raise RuntimeError(f"Provider count mismatch: {name}")
                profile_name = "ai-daily" if args.profile == "ai-daily" else "ai-core"
                contract_spec = manifest.get("semantic_contract")
                if not contract_spec or contract_spec.get("path") != "sources/semantic-contracts.json":
                    raise RuntimeError("Manifest missing semantic contract")
                contracts = load_contracts(root, manifest)
                contract = contracts.get("profiles", {}).get(profile_name)
                if not contract:
                    raise RuntimeError(f"Missing semantic contract profile: {profile_name}")
                positive = list(contract.get("must_match", []))
                negative = list(contract.get("must_not_match", []))
                selected_vendors = set(manifest["profiles"][profile_name]["members"])
                positive += [r.split(",")[1].split("/")[0] for r in (root / "rules/surge/openai-voice-ip.list").read_text(encoding="utf-8").splitlines() if r.startswith("IP-CIDR,")][:1]
                core = [Rule.from_text(row["rule"]) for row in manifest["provenance"]
                        if row["tier"] == "core" and row["vendor"] in selected_vendors]
                representatives = set()
                for row in manifest["provenance"]:
                    rule = Rule.from_text(row["rule"])
                    if rule.kind in {"DOMAIN", "DOMAIN-SUFFIX"}:
                        representatives.add(rule.value)
                        if rule.kind == "DOMAIN-SUFFIX":
                            representatives.update({"probe." + rule.value, rule.value + ".attacker.invalid", "not-" + rule.value})
                for host in sorted(representatives - set(positive) - set(negative)):
                    (positive if any(rule.matches(host) for rule in core) else negative).append(host)
                cases = []
                for expected, hosts in ((True, positive), (False, negative)):
                    for host in hosts:
                        actual = probe(port, host)
                        cases.append({"host": host, "expected_core_or_voice": expected, "matched": actual})
                        if actual != expected:
                            raise RuntimeError(f"Routing mismatch: {host}, expected={expected}, actual={actual}")
                refresh_report = verify_http_refresh(opener, controller, port, base / "providers", selected[0])
                report = {"engine_label": args.engine_label, "embedded_listener_controller_setup": embedded_listener_started, "http_provider_refresh": refresh_report, "engine": version, "provider_count": len(providers), "routing_case_count": len(cases), "cases": cases, "result": "PASS", "scope": "Isolated engine and real HTTP provider updates; NOT FlClash UI, Surge runtime or remote AI service connectivity"}
                report["profile"] = args.profile
                (work / "mihomo-validation.json").write_text(json_text(report), encoding="utf-8")
                (work / f"{args.engine_label}-validation-{args.profile}.json").write_text(json_text(report), encoding="utf-8")
                print(f"PASS ({args.profile}): {len(providers)} providers loaded; {len(cases)} real-engine routing probes; no remote AI requests")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                capture.shutdown()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
