"""Pinned official redirects, retained timestamps and readback deadline regressions."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import intake
import release
import rules
import sync

URL = 'https://help.openai.com/en/articles/9247338'
CANONICAL = URL + '-network-recommendations-for-chatgpt-errors-on-web-and-apps'


class OfficialFetchBudgetTests(unittest.TestCase):
    @staticmethod
    def denied(url):
        raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)

    def test_approved_canonical_redirect_recovers_and_closes_both_responses(self):
        calls, closed = [], []
        def get(url, **kw):
            calls.append(url)
            kw['content_callback'](b'discard' if len(calls) == 1 else b'official')
            return types.SimpleNamespace(status_code=302 if len(calls) == 1 else 200,
                headers={'Location': CANONICAL} if len(calls) == 1 else {},
                raise_for_status=lambda: None, close=lambda: closed.append(url))
        with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=types.SimpleNamespace(get=get))}):
            self.assertEqual(intake.fetch_official({'url': URL}, self.denied), (b'official', 'browser-compatible-https'))
        self.assertEqual(calls, [URL, CANONICAL])
        self.assertEqual(closed, calls)

    def test_unsafe_redirect_is_rejected_before_sending_to_target(self):
        for target in ('http://help.openai.com/path','ftp://help.openai.com/path',
                       'https://help.openai.com.evil.test/path','https://user@help.openai.com/path',
                       'https://help.openai.com:444/path','https://[malformed'):
            with self.subTest(target=target):
                calls=[]
                def get(url, **kw):
                    calls.append(url)
                    return types.SimpleNamespace(status_code=302,headers={'Location':target},close=lambda:None)
                with patch.dict(sys.modules,{'curl_cffi':types.SimpleNamespace(requests=types.SimpleNamespace(get=get))}), \
                        self.assertRaises(OSError):
                    intake.fetch_official({'url':URL}, self.denied)
                self.assertEqual(calls,[URL])

    def test_failure_trace_keeps_status_and_location(self):
        trace=[]
        def get(url, **kw):
            return types.SimpleNamespace(status_code=302,headers={'Location':'http://help.openai.com/path'},close=lambda:None)
        with patch.dict(sys.modules,{'curl_cffi':types.SimpleNamespace(requests=types.SimpleNamespace(get=get))}),self.assertRaises(OSError):
            intake.fetch_official({'url':URL}, self.denied, diagnostics=trace)
        self.assertEqual([row['status'] for row in trace],[403,302])
        self.assertEqual(trace[-1]['location'],'http://help.openai.com/path')

    def test_last_success_is_retained_on_later_failure_without_changing_facts(self):
        source=dict(id='fixture',url=URL,vendor='fixture',format='html',sections=['Network'],
                    required_hosts=['api.example.com'],min_hosts=1)
        page=b'<h2>Network</h2><p>api.example.com</p>'
        doc=intake.extract_document(source,page)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'sources').mkdir()
            (root/'sources/official.json').write_text(json.dumps({'sources':[source]}))
            baseline={'schema':1,'documents':{'fixture':doc}}
            (root/'sources/official-state.json').write_text(json.dumps(baseline))
            fresh,report=intake.refresh_official(root,lambda url:page)
            stamp=report['sources']['fixture']['last_success_at']
            self.assertTrue(stamp.endswith('Z'))
            self.assertEqual(fresh['documents'],baseline['documents'])
            (root/'sources/official-state.json').write_text(json.dumps(fresh))
            def fail(url):raise urllib.error.HTTPError(url,503,'Unavailable',{},None)
            retained,report=intake.refresh_official(root,fail)
        self.assertEqual(retained,fresh)
        self.assertEqual(report['sources']['fixture']['last_success_at'],stamp)
        self.assertEqual(report['sources']['fixture']['diagnostics'][0]['status'],503)

    def test_late_success_cannot_write_a_readback_after_deadline(self):
        now=[100.0]
        expected={'bundles':{}}
        payload=rules.json_text(expected).encode()
        def get(url):
            now[0]+=2
            return payload
        with tempfile.TemporaryDirectory() as td,patch.object(release.time,'monotonic',side_effect=lambda:now[0]):
            root=Path(td)
            with self.assertRaises(TimeoutError):
                release.downloaded_rules(root,'a'*40,expected,get=get,max_wait=1)
            self.assertFalse((root/'rules/manifest.json').exists())

    def test_real_fetch_timeout_uses_remaining_readback_budget(self):
        class Response(io.BytesIO):
            headers={}
            status=200
            def geturl(self):return 'https://raw.githubusercontent.com/NET86/rules/main/file'
        response=Response(b'body')
        opened=types.SimpleNamespace(open=lambda request, timeout: self.assertEqual(timeout,5) or response)
        with patch.object(sync.time,'monotonic',return_value=100),patch.object(sync.urllib.request,'build_opener',return_value=opened):
            self.assertEqual(sync.fetch(response.geturl(),deadline=105),b'body')


if __name__=='__main__':unittest.main()
