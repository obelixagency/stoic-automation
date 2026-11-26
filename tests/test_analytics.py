"""Offline tests for analytics + token derivation. No network; synthetic data only."""
import datetime as dt, json, os, sys, tempfile, types, unittest
from unittest.mock import Mock, patch

transport = types.ModuleType('requests')
transport.get = Mock(side_effect=AssertionError('unexpected network call'))
transport.post = Mock(side_effect=AssertionError('unexpected network call'))
_real = sys.modules.get('requests')
sys.modules['requests'] = transport
import analytics, meta_api, publish, watchdog
# Let other test modules import their own fresh copies against their own transport stub.
for _m in ('analytics', 'meta_api', 'publish', 'watchdog'):
    sys.modules.pop(_m, None)
if _real is not None: sys.modules['requests'] = _real
else: sys.modules.pop('requests', None)

CANARY = "SYNTHETIC_TOKEN_123"


def utc(s): return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


class Matching(unittest.TestCase):
    def item(self, attempt="2026-11-18T19:18:59"):
        return {"hook": "Hook A", "attempt": utc(attempt)}

    def test_matches_same_hook_shortly_after_attempt(self):
        media = [{"id": "x1", "time": utc("2026-11-18T19:20:00"), "text": "Hook A\n\nbody"}]
        self.assertEqual(analytics.match(self.item(), media, set())["id"], "x1")

    def test_ignores_same_hook_on_another_day(self):
        media = [{"id": "old", "time": utc("2026-11-11T19:20:00"), "text": "Hook A"}]
        self.assertIsNone(analytics.match(self.item(), media, set()))

    def test_same_media_not_used_twice(self):
        media = [{"id": "x1", "time": utc("2026-11-18T19:20:00"), "text": "Hook A"}]
        self.assertIsNone(analytics.match(self.item(), media, {"x1"}))


class Collect(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        analytics.INSIGHTS = os.path.join(self.d, "insights_log.json")
        self.log = {"2026-11-10": {"morning": {"instagram_reel": {"status": "ok", "last_attempt": "2026-11-10T11:31:00+00:00"},
                                               "facebook_reel": {"status": "failed", "last_attempt": "2026-11-10T11:31:00+00:00"}}}}
        plan = {"posts": [{"slot": "morning", "item_id": "A", "type": "quote_reel", "caption": "Hook A\n\nrest"}]}

    def test_scores_instagram_and_records_local_slot_times(self):
        def get(path, token, **kw):
            if path == "I/media":
                return True, {"data": [{"id": "m1", "timestamp": "2026-11-10T12:32:00+0000", "caption": "Hook A", "media_product_type": "REELS"}]}
            if path == "m1/insights":
                return True, {"data": [{"name": "views", "values": [{"value": 900}]}, {"name": "reach", "values": [{"value": 700}]}]}
            return False, "http_400_code_100"
        # drive collect() with published_items patched directly
        with patch.object(analytics, "published_items", return_value=[{
                "date": "2026-11-10", "slot": "morning", "platform": "instagram_reel", "type": "quote_reel", "hook": "Hook A",
                "slot_utc": utc("2026-11-10T12:30:00"), "attempt": utc("2026-11-10T12:31:00")}]), \
             patch.object(analytics.M, "get", side_effect=get):
            notes = analytics.collect(now=utc("2026-11-14T00:00:00"), token=CANARY, page_id="P", ig_id="I")
        e = json.load(open(analytics.INSIGHTS))["entries"]["2026-11-10|morning|instagram_reel"]
        self.assertEqual((e["views"], e["reach"]), (900, 700))
        self.assertEqual(e["slot_local"], "2026-11-10 07:30 EST")      # 12:30Z in November = 07:30 New York
        self.assertEqual(e["slot_cairo"], "2026-11-10 14:30")          # Cairo is UTC+2 in November
        self.assertIn("scored_on", e)
        self.assertNotIn("m1", json.dumps(e)); self.assertNotIn(CANARY, json.dumps(e))
        self.assertEqual(notes, [])

    def test_dst_summer_slot_local_is_still_0730(self):
        slot_utc = watchdog.slot_time_utc("2026-07-10", "07:30")
        self.assertEqual(slot_utc.astimezone(analytics.ET).strftime("%H:%M %Z"), "07:30 EDT")

    def test_platform_failure_leaves_a_note_without_secrets(self):
        item = {"date": "2026-11-10", "slot": "morning", "platform": "facebook_reel", "type": "quote_reel", "hook": "Hook A",
                "slot_utc": utc("2026-11-10T12:30:00"), "attempt": utc("2026-11-10T12:31:00")}
        with patch.object(analytics, "published_items", return_value=[item]), \
             patch.object(analytics.M, "get", return_value=(False, "http_400_code_100")):
            notes = analytics.collect(now=utc("2026-11-14T00:00:00"), token=CANARY, page_id="P", ig_id="I")
        self.assertTrue(any("facebook_reel" in n and "http_400_code_100" in n for n in notes))
        self.assertNotIn(CANARY, " ".join(notes))

    def test_too_old_never_fetched_and_frozen_not_refetched(self):
        item = {"date": "2026-11-10", "slot": "morning", "platform": "instagram_reel", "type": "q", "hook": "h",
                "slot_utc": utc("2026-11-10T12:30:00"), "attempt": utc("2026-11-10T12:31:00")}
        json.dump({"entries": {"2026-11-10|morning|instagram_reel": {"scored_on": "x", "frozen": True, "views": 5}}}, open(analytics.INSIGHTS, "w"))
        with patch.object(analytics, "published_items", return_value=[item]), patch.object(analytics.M, "get") as g:
            analytics.collect(now=utc("2026-11-30T00:00:00"), token=CANARY, page_id="P", ig_id="I")
        g.assert_not_called()


class Report(unittest.TestCase):
    def test_median_total_per_platform_and_slot(self):
        store = {"entries": {f"d{i}": {"platform": "instagram_reel", "slot": "morning", "type": "quote_reel", "views": v,
                                  "slot_utc": "2026-11-10T12:30:00+00:00", "scored_on": "2026-11-14T00:00:00+00:00"}
                             for i, v in enumerate([100, 300, 200])}}
        r = analytics.build_report(store)
        self.assertIn("| instagram_reel | morning | 3 | 200 | 200 | 600 |", r)


class TokenDerivation(unittest.TestCase):
    def setUp(self): publish._PAGE_TOKEN.clear()

    def test_prefers_derived_page_token_and_never_prints_it(self):
        env = {"META_SYSTEM_TOKEN": "SYS", "FB_PAGE_ID": "P", "FB_PAGE_TOKEN": "OLD", "IG_USER_ID": "I"}
        with patch.dict(os.environ, env), patch.object(publish.meta_api, "get", return_value=(True, {"access_token": CANARY})):
            self.assertEqual(publish._ig(), ("I", CANARY))
            self.assertEqual(publish._fb_page(), ("P", CANARY))

    def test_falls_back_to_stored_page_token(self):
        env = {"META_SYSTEM_TOKEN": "SYS", "FB_PAGE_ID": "P", "FB_PAGE_TOKEN": "OLD"}
        with patch.dict(os.environ, env), patch.object(publish.meta_api, "get", return_value=(False, "http_400_code_190")):
            self.assertEqual(publish._fb_page(), ("P", "OLD"))

    def test_metric_names_are_the_new_ones(self):
        self.assertEqual(meta_api.PAGE_REACH_METRIC, "page_total_media_view_unique")
        self.assertEqual(meta_api.POST_REACH_METRIC, "post_total_media_view_unique")
        self.assertIn("blue_reels_play_count", meta_api.FB_REEL_METRICS)
        self.assertIn("post_video_avg_time_watched", meta_api.FB_REEL_METRICS)


if __name__ == "__main__":
    unittest.main()


class Engagement(unittest.TestCase):
    def setUp(self): publish._PAGE_TOKEN.clear()

    def test_caption_first_line_is_an_ask_then_a_tag_share_save_call(self):
        import random, selector
        sel = selector.Selector(selector.load_library("library/library_*.json"))
        plan = sel.pick_day("2026-12-01", [])
        for p in plan["posts"]:
            if not p["caption"]:
                continue
            lines = p["caption"].split("\n")
            self.assertTrue(lines[0].endswith(("?", ".")) and ("one" in lines[0].lower() or "type" in lines[0].lower()
                            or "rate" in lines[0].lower() or "number" in lines[0].lower() or "word" in lines[0].lower()), lines[0])
            self.assertTrue(any(w in lines[1].lower() for w in ("tag", "save", "share")), lines[1])
            self.assertTrue(p["first_comment"] and "{" not in p["first_comment"])

    def test_first_comment_posted_after_reel_and_failure_never_breaks_publish(self):
        env = {"FB_PAGE_ID": "P", "IG_USER_ID": "I", "FB_PAGE_TOKEN": "T"}
        resp_ok = Mock(status_code=200, json=Mock(return_value={"id": "c1"}))
        with patch.dict(os.environ, env), patch.dict(publish.DISPATCH, instagram_reel=Mock(return_value="MEDIA1")), \
             patch.object(publish.requests, "post", return_value=resp_ok) as post:
            self.assertEqual(publish.publish("instagram_reel", "f", "cap", "Q?"), (True, {"published": True}))
        self.assertTrue(post.call_args[0][0].endswith("/MEDIA1/comments"))
        self.assertEqual(post.call_args[1]["data"]["message"], "Q?")
        resp_bad = Mock(status_code=400, json=Mock(return_value={"error": {"message": CANARY}}))
        with patch.dict(os.environ, env), patch.dict(publish.DISPATCH, facebook_reel=Mock(return_value="V1")), \
             patch.object(publish.requests, "post", return_value=resp_bad):
            self.assertEqual(publish.publish("facebook_reel", "f", "cap", "Q?"), (True, {"published": True}))

    def test_stories_get_no_comment(self):
        with patch.dict(publish.DISPATCH, instagram_story=Mock(return_value="S1")), \
             patch.object(publish.requests, "post") as post:
            publish.publish("instagram_story", "f", "cap", "Q?")
        post.assert_not_called()


    def test_young_videos_are_left_out_of_the_report(self):
        store = {"entries": {"a": {"platform": "instagram_reel", "slot": "morning", "type": "q", "views": 5,
                                   "slot_utc": "2026-11-10T12:30:00+00:00", "scored_on": "2026-11-11T00:00:00+00:00"}}}
        self.assertNotIn("| instagram_reel | morning", analytics.build_report(store))


class TikTokPaused(unittest.TestCase):
    def test_paused_platform_is_never_published_or_escalated(self):
        d = tempfile.mkdtemp()
        plan = {"date": "2026-11-20", "posts": [{"slot": "morning", "item_id": "A", "formats": ["tiktok", "youtube_short"], "caption": "c"}]}
        json.dump(plan, open(os.path.join(d, "plan_2026-11-20.json"), "w"))
        calls = []
        with patch.object(watchdog, "HERE", d), patch.object(watchdog, "LOG", os.path.join(d, "log.json")), \
             patch.object(watchdog, "paused_platforms", return_value={"tiktok"}), \
             patch.object(watchdog, "platform_file", return_value="f.mp4"), \
             patch.object(watchdog.PUB, "publish", side_effect=lambda p, *a, **k: calls.append(p) or (True, {"published": True})):
            json.dump({"slots": [{"id": "morning", "time_et": "07:30"}]}, open(os.path.join(d, "schedule.json"), "w"))
            rc = watchdog.run("2026-11-20", now=utc("2026-11-20T23:00:00"))
        self.assertEqual(calls, ["youtube_short"]); self.assertEqual(rc, 0)
