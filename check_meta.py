"""Read-only health check of the Meta token: can it publish and read insights/comments?
Prints PASS/FAIL per capability with a short code only. Never prints tokens, IDs or message text.
"""
import os, sys
import meta_api as M


def run():
    page_id, ig_id = os.environ.get("FB_PAGE_ID"), os.environ.get("IG_USER_ID")
    sys_tok = os.environ.get("META_SYSTEM_TOKEN")
    results = []
    def rec(name, ok, note=""):
        results.append((name, ok)); print(f'{"PASS" if ok else "FAIL"}  {name}  {"" if ok else note}')
    if not (sys_tok and page_id and ig_id):
        rec("secrets_present", False, "missing_secret"); return 1
    ptok = M.page_token(sys_tok, page_id)
    rec("page_token_from_system_token", bool(ptok), "cannot_derive")
    if not ptok: return 1
    ok, d = M.get("me/permissions", sys_tok)
    granted = {x.get("permission") for x in d.get("data", []) if x.get("status") == "granted"} if ok else set()
    rec("fb_publish_permission(pages_manage_posts granted)", "pages_manage_posts" in granted, "not_granted" if ok else d)
    ok, d = M.get(f"{ig_id}/content_publishing_limit", ptok, fields="quota_usage")
    rec("ig_publish_access", ok, d)
    ok, d = M.get(f"{page_id}/insights", ptok, metric=M.PAGE_REACH_METRIC, period="day")
    rec("page_insights(page_total_media_view_unique)", ok, d)
    ok, d = M.get(f"{ig_id}/insights", ptok, metric="reach", period="day")
    rec("ig_account_insights(reach)", ok, d)
    media = M.ig_media(ig_id, ptok, limit=5)
    rec("ig_media_list", bool(media), "empty_or_denied")
    reels = [m for m in media if m.get("media_product_type") == "REELS"] or media
    if reels:
        ok, s = M.ig_media_stats(reels[0]["id"], ptok)
        rec("ig_media_insights(reach,views,...)", ok, s)
        ok, d = M.get(f"{reels[0]['id']}/comments", ptok, limit=1)
        rec("ig_comments_read", ok, d)
    fr = M.fb_reels(page_id, ptok, limit=5)
    rec("fb_reels_list", bool(fr), "empty_or_denied")
    if fr:
        ok, s = M.fb_reel_stats(fr[0]["id"], ptok)
        rec("fb_reel_insights(blue_reels_play_count)", ok, s)
        ok, d = M.get(f"{fr[0]['id']}/comments", ptok, limit=1)
        rec("fb_comments_read", ok, d)
    ok, d = M.get(f"{page_id}/posts", ptok, fields="id", limit=1)
    posts = d.get("data", []) if ok else []
    if posts:
        ok, d = M.get(f"{posts[0]['id']}/insights", ptok, metric=M.POST_REACH_METRIC)
        rec("fb_post_reach(post_total_media_view_unique)", ok, d)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(run())
