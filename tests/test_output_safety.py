"""Offline regression checks: synthetic credentials only, no external calls."""
import contextlib
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

# Deliberately isolate the requests transport even when requests is installed.
transport = types.ModuleType('requests')
transport.get = Mock(side_effect=AssertionError('unexpected network call'))
transport.post = Mock(side_effect=AssertionError('unexpected network call'))
sys.modules['requests'] = transport
import publish
import watchdog

CANARY = 'SYNTHETIC_SECRET_DO_NOT_OUTPUT_123'

class OutputSafety(unittest.TestCase):
    def test_exceptions_and_success_bodies_never_escape(self):
        for result in ({'access_token': CANARY}, CANARY, {'ntfy_topic': CANARY}):
            with patch.dict(publish.DISPATCH, fake=Mock(return_value=result)):
                self.assertEqual(publish.publish('fake', 'file', ''), (True, {'published': True}))
        for exc in (RuntimeError(CANARY), publish.NotConnected(CANARY)):
            with patch.dict(publish.DISPATCH, fake=Mock(side_effect=exc)):
                ok, detail = publish.publish('fake', 'file', '')
                self.assertFalse(ok)
                self.assertNotIn(CANARY, json.dumps(detail))

    def test_provider_errors_are_fixed_text(self):
        for response in (Mock(status_code=400, json=Mock(return_value={'error': CANARY})),
                         Mock(status_code=500, text=CANARY, json=Mock(side_effect=ValueError(CANARY)))):
            with self.assertRaises(RuntimeError) as err:
                publish._check(response)
            self.assertNotIn(CANARY, str(err.exception))

    def test_oauth_failure_and_generated_token(self):
        env = {k: CANARY for k in ('YT_CLIENT_ID','YT_CLIENT_SECRET','YT_REFRESH_TOKEN',
                                  'TIKTOK_CLIENT_KEY','TIKTOK_CLIENT_SECRET','TIKTOK_REFRESH_TOKEN')}
        for fn in (publish._yt_access_token, publish._tiktok_access_token):
            with patch.dict(os.environ, env), patch.object(transport, 'post', return_value=Mock(json=lambda: {'error': CANARY})):
                with self.assertRaises(RuntimeError) as err: fn()
                self.assertNotIn(CANARY, str(err.exception))
            with patch.dict(os.environ, env), patch.object(transport, 'post', return_value=Mock(json=lambda: {'access_token': CANARY})):
                self.assertEqual(fn(), CANARY)  # credential still works in memory

    def test_instagram_get_auth_not_in_query(self):
        response = Mock(status_code=200, json=lambda: {'status_code': 'FINISHED'})
        with patch.object(transport, 'get', return_value=response) as get:
            publish._ig_wait_ready('123', CANARY, tries=1)
        self.assertNotIn('access_token', get.call_args.kwargs['params'])
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer '+CANARY)

    def test_private_notification_topic_not_returned(self):
        with patch.dict(os.environ, NTFY_TOPIC=CANARY), patch.object(transport, 'post', return_value=Mock(status_code=200)):
            self.assertEqual(publish._notify_ntfy_tiktok('a.mp4','caption'), {'notification_sent': True})

    def test_historical_sanitization_preserves_dedup_and_retries(self):
        original = {'2026-10-24': {'morning': {
            'tiktok': {'status':'ok','detail':{'platform_ref':{'ntfy_topic':CANARY}},'attempts':2,'last_attempt':'2026-10-24T12:00:00+00:00'},
            'youtube_short': {'status':'failed','detail':{'error':'publish_failed','message':CANARY},'attempts':3}}}}
        clean=watchdog.sanitize_publish_log(copy.deepcopy(original))
        self.assertNotIn(CANARY, json.dumps(clean))
        for platform in original['2026-10-24']['morning']:
            for key in ('status','attempts','last_attempt'):
                self.assertEqual(clean['2026-10-24']['morning'][platform].get(key),original['2026-10-24']['morning'][platform].get(key))

    def test_persisted_output_and_success_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'schedule.json').write_text(json.dumps({'slots':[{'id':'morning','time_et':'07:30'}]}))
            (p/'plan_2026-10-24.json').write_text(json.dumps({'posts':[{'slot':'morning','item_id':'a','formats':['tiktok','youtube_short']}]}))
            log={'2026-10-24':{'morning':{'tiktok':{'status':'ok','attempts':1,'detail':{'platform_ref':CANARY}}}}}
            (p/'publish_log.json').write_text(json.dumps(log))
            with patch.object(watchdog,'HERE',tmp), patch.object(watchdog,'LOG',str(p/'publish_log.json')), patch.object(watchdog,'platform_file',return_value='fake.mp4'), patch.dict(publish.DISPATCH,youtube_short=Mock(side_effect=RuntimeError(CANARY))), patch.object(publish,'publish',wraps=publish.publish) as call, contextlib.redirect_stdout(io.StringIO()) as out:
                watchdog.run('2026-10-24',dt.datetime(2026,10,24,16,tzinfo=dt.timezone.utc))
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],'youtube_short')
            self.assertNotIn(CANARY,out.getvalue()+(p/'publish_log.json').read_text())

if __name__ == '__main__': unittest.main()
