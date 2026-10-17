"""Reuse successful native checks only within one immutable publication process.

Every directory is still byte/semantically verified. No persisted cache is trusted,
no network/readback/ref check is skipped, and failures never populate this cache.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys

from verify_rules import verify


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class RuntimeGateSession:
    def __init__(self, native_gate, source_root):
        self.native_gate = native_gate
        self.source_root = Path(source_root)
        self.source_version = self._source_version()
        self._entries = {}
        self.stats = {'native_executions': 0, 'reused_checks': 0, 'scope': 'current-process-only'}

    def _source_version(self):
        files = sorted((self.source_root / 'scripts').glob('*.py'))
        if not files:
            raise ValueError('Missing verifier source snapshot')
        return [(p.name, digest_file(p)) for p in files]

    def _key(self, root, binaries, profile):
        if self._source_version() != self.source_version:
            raise RuntimeError('Verifier source changed during publication')
        manifest = json.loads((root / 'rules/manifest.json').read_text(encoding='utf-8'))
        paths = {'rules/manifest.json', manifest['semantic_contract']['path']}
        for bundle in manifest['bundles'].values():
            paths.update(spec['path'] for spec in bundle.values())
        surface = []
        for relative in sorted(paths):
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError('Runtime input escapes validation root')
            surface.append((relative, digest_file(path)))
        identity = {'version': 1, 'profile': profile, 'source': self.source_version,
                    'python': sys.version, 'platform': sys.platform, 'os': os.name,
                    'artifacts': surface,
                    'binaries': [(label, str(Path(binary).resolve()), digest_file(binary)) for label, binary in binaries]}
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def __call__(self, root, binaries, profile='ai-daily'):
        root = Path(root)
        binaries = list(binaries)
        labels = [label for label, _ in binaries]
        if (profile not in {'ai-daily', 'split', 'ai-cn'} or not labels or len(set(labels)) != len(labels)
                or any(not isinstance(label, str) or not re.fullmatch(r'[a-z0-9-]+', label) for label in labels)):
            raise ValueError('Invalid native validation identity')
        # Always check actual newly fetched bytes, not only the claimed manifest.
        verify(root)
        key = self._key(root, binaries, profile)
        filenames = [f'{label}-validation-{profile}.json' for label in labels]
        work = root / '.work'
        work.mkdir(exist_ok=True)
        reused = key in self._entries
        if reused:
            reports = self._entries[key]
        else:
            # Prevent a zero exit that produced no report from inheriting stale PASS.
            for name in filenames:
                (work / name).unlink(missing_ok=True)
            self.stats['native_executions'] += 1
            self.native_gate(root, binaries, profile)
            verify(root)
            if self._key(root, binaries, profile) != key:
                raise RuntimeError('Runtime inputs changed during native validation')
            collected = []
            for label, name in zip(labels, filenames):
                raw = (work / name).read_bytes()
                report = json.loads(raw)
                cases = report.get('cases') if isinstance(report, dict) else None
                if (not isinstance(report, dict) or report.get('result') != 'PASS'
                        or report.get('engine_label') != label or report.get('profile') != profile
                        or type(report.get('routing_case_count')) is not int or report['routing_case_count'] <= 0
                        or not isinstance(cases, list) or len(cases) != report['routing_case_count']
                        or any(not isinstance(case, dict)
                               or type(case.get('expected_core_or_voice')) is not bool
                               or type(case.get('matched')) is not bool
                               or case['matched'] != case['expected_core_or_voice'] for case in cases)):
                    raise ValueError('Missing or invalid native success evidence')
                collected.append((name, raw))
            reports = tuple(collected)
        # Raw in-memory evidence is immutable; each destination gets its own
        # explicit execution/reuse attribution, never a claim of a fresh run.
        for name, raw in reports:
            report = json.loads(raw)
            report['runtime_gate'] = {'key': key, 'execution': 'reused' if reused else 'executed',
                                      'cache_scope': 'current-process-only'}
            (work / name).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if self._key(root, binaries, profile) != key:
            self._entries.pop(key, None)
            raise RuntimeError('Runtime inputs changed while recording evidence')
        if reused:
            self.stats['reused_checks'] += 1
        else:
            self._entries[key] = reports
        return {'key': key, 'execution': 'reused' if reused else 'executed'}
