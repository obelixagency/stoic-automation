"""Platform publishing. Facebook and Instagram call the real Graph API now that those accounts are
connected. TikTok and YouTube are still stubs until those accounts are connected - same pattern:
each function checks its own secrets, nothing else in the pipeline needs to change when they're filled in.

Facebook: uses direct file upload (multipart), so no public hosting is needed.
Instagram: the Graph API only accepts a public image_url/video_url (it fetches the file itself), so the
rendered file's public URL is built from GitHub Pages serving the `media-public` branch - see
_public_url() and the "Publish today's media" step in .github/workflows/watchdog.yml. GitHub Pages must
be enabled once for that branch (Settings -> Pages -> branch: media-public -> /).
"""
import os, time
import requests

GRAPH = "https://graph.facebook.com/v21.0"


class NotConnected(Exception):
    pass


def _need(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing: raise NotConnected(f"missing secrets: {', '.join(missing)}")


def _fb_page():
    _need("FB_PAGE_ID", "FB_PAGE_TOKEN")
    return os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]


def _ig():
    _need("IG_USER_ID", "FB_PAGE_TOKEN")   # Instagram Graph API calls are authenticated with the linked Page's token
    return os.environ["IG_USER_ID"], os.environ["FB_PAGE_TOKEN"]


def _check(resp):
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status(); raise RuntimeError(f"non-JSON response: {resp.text[:200]}")
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(data.get("error", data))
    return data


def _public_url(path):
    repo = os.environ.get("GITHUB_REPOSITORY")   # "owner/repo", set automatically by GitHub Actions
    if not repo: raise RuntimeError("GITHUB_REPOSITORY not set - can't build a public URL for Instagram")
    owner, name = repo.split("/")
    return f"https://{owner}.github.io/{name}/{os.path.basename(path)}"


# ---------------- Facebook (direct file upload, no public URL needed) ----------------
def publish_facebook_post(path, caption):
    page_id, token = _fb_page()
    with open(path, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/photos", data={"caption": caption, "access_token": token}, files={"source": f})
    return _check(r)["id"]


def publish_facebook_reel(path, caption):
    """Uploads as a standard Page video post. (Landing specifically in the Facebook Reels tray needs the
    separate resumable Reels upload API; this still publishes the video to the Page's feed and video tab.)"""
    page_id, token = _fb_page()
    with open(path, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/videos", data={"description": caption, "access_token": token}, files={"source": f})
    return _check(r)["id"]


def publish_facebook_story(path, caption):
    page_id, token = _fb_page()
    is_video = str(path).endswith(".mp4")
    with open(path, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/{'videos' if is_video else 'photos'}",
                           data={"published": "false", "access_token": token}, files={"source": f})
    media_id = _check(r)["id"]
    r2 = requests.post(f"{GRAPH}/{page_id}/{'video_stories' if is_video else 'photo_stories'}",
                        data={("video_id" if is_video else "photo_id"): media_id, "access_token": token})
    return _check(r2)


def publish_facebook_carousel(paths, caption):
    """Facebook Pages have no native multi-image carousel post; publish each image as its own post,
    same as a human page manager would."""
    return [publish_facebook_post(p, caption if i == 0 else "") for i, p in enumerate(paths)]


# ---------------- Instagram (needs a public URL - see _public_url) ----------------
def _ig_wait_ready(creation_id, token, tries=10, wait_s=3):
    for _ in range(tries):
        status = _check(requests.get(f"{GRAPH}/{creation_id}", params={"fields": "status_code", "access_token": token}))
        if status.get("status_code") == "FINISHED": return
        time.sleep(wait_s)
    raise RuntimeError(f"Instagram container {creation_id} never finished processing")


def _ig_create_and_publish(media_params):
    ig_id, token = _ig()
    r = requests.post(f"{GRAPH}/{ig_id}/media", data={**media_params, "access_token": token})
    creation_id = _check(r)["id"]
    _ig_wait_ready(creation_id, token)
    r2 = requests.post(f"{GRAPH}/{ig_id}/media_publish", data={"creation_id": creation_id, "access_token": token})
    return _check(r2)["id"]


def publish_instagram_post(path, caption):
    return _ig_create_and_publish({"image_url": _public_url(path), "caption": caption})


def publish_instagram_reel(path, caption):
    return _ig_create_and_publish({"media_type": "REELS", "video_url": _public_url(path), "caption": caption})


def publish_instagram_story(path, caption):
    is_video = str(path).endswith(".mp4")
    params = {"media_type": "STORIES", ("video_url" if is_video else "image_url"): _public_url(path)}
    return _ig_create_and_publish(params)


def publish_instagram_carousel(paths, caption):
    ig_id, token = _ig()
    item_ids = []
    for p in paths:
        r = requests.post(f"{GRAPH}/{ig_id}/media", data={"image_url": _public_url(p), "is_carousel_item": "true", "access_token": token})
        item_ids.append(_check(r)["id"])
    return _ig_create_and_publish({"media_type": "CAROUSEL", "children": ",".join(item_ids), "caption": caption})


# ---------------- not connected yet ----------------
def publish_tiktok(path, caption): _need("TIKTOK_REFRESH_TOKEN"); raise NotConnected("TikTok not connected yet (drafts-only until app review passes)")
def publish_youtube_short(path, caption): _need("YT_REFRESH_TOKEN", "YT_CHANNEL_ID"); raise NotConnected("YouTube not connected yet")

DISPATCH = {
    "facebook_reel": publish_facebook_reel, "facebook_post": publish_facebook_post, "facebook_story": publish_facebook_story,
    "facebook_carousel": publish_facebook_carousel,
    "instagram_reel": publish_instagram_reel, "instagram_post": publish_instagram_post, "instagram_story": publish_instagram_story,
    "instagram_carousel": publish_instagram_carousel,
    "tiktok": publish_tiktok, "youtube_short": publish_youtube_short,
}


def publish(platform, path_or_paths, caption):
    """path_or_paths: the file (or, for *_carousel platforms, the ordered list of files) render_day.py made.
    Returns (ok, detail)."""
    try:
        ref = DISPATCH[platform](path_or_paths, caption)
        return True, {"platform_ref": ref}
    except NotConnected as e:
        return False, {"error": "not_connected", "message": str(e)}
    except Exception as e:
        return False, {"error": "publish_failed", "message": str(e)}
