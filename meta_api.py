"""Read-only Meta Graph helpers for analytics and health checks.

Auth: one never-expiring System User token (secret META_SYSTEM_TOKEN) is exchanged at runtime for the
Page token. Nothing here prints or returns tokens, IDs, captions or provider messages: callers get
numbers and short fixed error labels only (this repo and its logs are public, see SECURITY_OUTPUTS.md).
"""
import os
import requests

GRAPH = "https://graph.facebook.com/v21.0"
# 2025 metric changes: *_impressions_unique returns code 100; the replacements are *_total_media_view_unique.
PAGE_REACH_METRIC = "page_total_media_view_unique"
POST_REACH_METRIC = "post_total_media_view_unique"
FB_REEL_METRICS = "blue_reels_play_count,post_video_avg_time_watched"
IG_MEDIA_METRICS = "reach,views,saved,shares,likes,comments"


def get(path, token, **params):
    """GET -> (ok, payload). On failure payload is a short label like 'http_400_code_100', never the body."""
    try:
        r = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=30)
        data = r.json()
    except Exception:
        return False, "request_failed"
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        return False, f"http_{r.status_code}_code_{err.get('code', 'x')}"
    return True, data


def page_token(system_token=None, page_id=None):
    """Page token derived from the system-user token; None if it cannot be derived."""
    system_token = system_token or os.environ.get("META_SYSTEM_TOKEN")
    page_id = page_id or os.environ.get("FB_PAGE_ID")
    if not (system_token and page_id):
        return None
    ok, data = get(page_id, system_token, fields="access_token")
    return data.get("access_token") if ok else None


def metric_values(data):
    """Flatten an insights response to {metric_name: number} (last value of each series)."""
    out = {}
    for m in data.get("data", []):
        vals = m.get("values") or []
        if vals:
            v = vals[-1].get("value")
        elif "total_value" in m:
            v = m["total_value"].get("value")
        else:
            continue
        if isinstance(v, (int, float)):
            out[m.get("name")] = v
    return out


def ig_media(ig_id, token, limit=50):
    ok, d = get(f"{ig_id}/media", token, fields="id,timestamp,media_product_type", limit=limit)
    return d.get("data", []) if ok else []


def ig_media_stats(media_id, token):
    ok, d = get(f"{media_id}/insights", token, metric=IG_MEDIA_METRICS)
    return (True, metric_values(d)) if ok else (False, d)


def fb_reels(page_id, token, limit=50):
    ok, d = get(f"{page_id}/video_reels", token, fields="id,created_time", limit=limit)
    return d.get("data", []) if ok else []


def fb_reel_stats(video_id, token):
    ok, d = get(f"{video_id}/video_insights", token, metric=FB_REEL_METRICS)
    return (True, metric_values(d)) if ok else (False, d)
