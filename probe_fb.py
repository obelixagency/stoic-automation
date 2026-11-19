"""One-off read-only probe: which FB video metrics return numbers for our latest videos? Prints numbers only."""
import os
import meta_api as M
tok = M.page_token()
pid = os.environ["FB_PAGE_ID"]
cands = ["blue_reels_play_count", "post_video_avg_time_watched", "total_video_views", "total_video_impressions",
         "total_video_impressions_unique", "total_video_avg_time_watched", "post_impressions_unique",
         "post_total_media_view_unique", "post_media_view"]
for label, path in (("reels_edge", f"{pid}/video_reels"), ("videos_edge", f"{pid}/videos")):
    ok, d = M.get(path, tok, fields="id,created_time,length", limit=4)
    print(label, "list_ok" if ok else f"list_fail {d}", len(d.get("data", [])) if ok else 0)
    for i, v in enumerate(d.get("data", [])[:4] if ok else []):
        for m in cands:
            ok2, r = M.get(f'{v["id"]}/video_insights', tok, metric=m)
            if ok2:
                print(f"  #{i} {label} {m} = {M.metric_values(r).get(m)}")
            else:
                print(f"  #{i} {label} {m} FAIL {r}")
ok, d = M.get(f"{pid}/posts", tok, fields="id,created_time", limit=3)
for i, p in enumerate(d.get("data", []) if ok else []):
    for m in ("post_total_media_view_unique", "post_media_view", "post_impressions_unique"):
        ok2, r = M.get(f'{p["id"]}/insights', tok, metric=m)
        print(f"  post#{i} {m} =", M.metric_values(r).get(m) if ok2 else f"FAIL {r}")
