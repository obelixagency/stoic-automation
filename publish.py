"""Platform publishing. Facebook and Instagram call the real Graph API now that those accounts are
connected. TikTok and YouTube are still stubs until those accounts are connected - same pattern:
each function checks its own secrets, nothing else in the pipeline needs to change when they're filled in.

Facebook: uses direct file upload (multipart), so no public hosting is needed.
Instagram: the Graph API only accepts a public image_url/video_url (it fetches the file itself), so
rendered media is also mirrored to the public `stoic-media` repo (GitHub Pages, enabled on its main
branch) and _public_url() points there - see the "Publish today's media" step in
.github/workflows/watchdog.yml. stoic-automation itself stays private; only rendered files ever leave it.
"""
import os, time, json, subprocess
import requests

GRAPH = "https://graph.facebook.com/v21.0"
MEDIA_REPO_OWNER = "obelixagency"
MEDIA_REPO_NAME = "stoic-media"


def _cover_offset_ms(path):
    """render.py fades every reel in from black over the first 0.5s, so frame 0 - the frame platforms
    default to for the cover/thumbnail - is always black. Point the cover at a moment near the end
    instead, where the full line of text is on screen and held (see `tail` in build_reel)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", path],
                              capture_output=True, text=True, timeout=15)
        return max(int(float(out.stdout.strip()) * 1000) - 300, 0)
    except Exception:
        return None


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
    return f"https://{MEDIA_REPO_OWNER}.github.io/{MEDIA_REPO_NAME}/{os.path.basename(path)}"


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
    data = {"description": caption, "access_token": token}
    offset = _cover_offset_ms(path)
    if offset is not None: data["thumb_offset"] = offset
    with open(path, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/videos", data=data, files={"source": f})
    return _check(r)["id"]


def _fb_video_story(path, page_id, token):
    """Facebook video stories use the 3-phase upload: start -> send the file to upload_url -> finish.
    (The generic /videos + video_stories(video_id) route fails with "upload_phase is required".)"""
    r = requests.post(f"{GRAPH}/{page_id}/video_stories", data={"upload_phase": "start", "access_token": token})
    d = _check(r)
    video_id, upload_url = d["video_id"], d["upload_url"]
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        u = requests.post(upload_url, headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}, data=f)
    _check(u)
    r3 = requests.post(f"{GRAPH}/{page_id}/video_stories",
                       data={"upload_phase": "finish", "video_id": video_id, "access_token": token})
    return _check(r3)

def publish_facebook_story(path, caption):
    page_id, token = _fb_page()
    if str(path).endswith(".mp4"):
        return _fb_video_story(path, page_id, token)
    with open(path, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/photos", data={"published": "false", "access_token": token}, files={"source": f})
    media_id = _check(r)["id"]
    r2 = requests.post(f"{GRAPH}/{page_id}/photo_stories", data={"photo_id": media_id, "access_token": token})
    return _check(r2)

def publish_facebook_carousel(paths, caption):
    """Facebook Pages have no native multi-image carousel post; publish each image as its own post,
    same as a human page manager would."""
    return [publish_facebook_post(p, caption if i == 0 else "") for i, p in enumerate(paths)]


# ---------------- Instagram (needs a public URL - see _public_url) ----------------
def _ig_wait_ready(creation_id, token, tries=40, wait_s=5):
    """Instagram processes videos asynchronously; reels/stories can take well over 30s, so wait up to ~200s
    and fail fast with Instagram's own error if the container reports ERROR/EXPIRED."""
    last = None
    for _ in range(tries):
        status = _check(requests.get(f"{GRAPH}/{creation_id}", params={"fields": "status_code,status", "access_token": token}))
        last = status
        code = status.get("status_code")
        if code == "FINISHED": return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram container {creation_id} failed: {status}")
        time.sleep(wait_s)
    raise RuntimeError(f"Instagram container {creation_id} never finished processing (last status: {last})")

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
    params = {"media_type": "REELS", "video_url": _public_url(path), "caption": caption}
    offset = _cover_offset_ms(path)
    if offset is not None: params["thumb_offset"] = offset
    return _ig_create_and_publish(params)


def publish_instagram_story(path, caption):
    is_video = str(path).endswith(".mp4")
    params = {"media_type": "STORIES", ("video_url" if is_video else "image_url"): _public_url(path)}
    if is_video:
        offset = _cover_offset_ms(path)
        if offset is not None: params["thumb_offset"] = offset
    return _ig_create_and_publish(params)


def publish_instagram_carousel(paths, caption):
    ig_id, token = _ig()
    item_ids = []
    for p in paths:
        r = requests.post(f"{GRAPH}/{ig_id}/media", data={"image_url": _public_url(p), "is_carousel_item": "true", "access_token": token})
        item_ids.append(_check(r)["id"])
    return _ig_create_and_publish({"media_type": "CAROUSEL", "children": ",".join(item_ids), "caption": caption})


# ---------------- TikTok ----------------
TIKTOK_API = "https://open.tiktokapis.com/v2"


def _tiktok_access_token():
    r = requests.post(f"{TIKTOK_API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = r.json()
    if "access_token" not in data: raise RuntimeError(data)
    return data["access_token"]


def _publish_tiktok_real(path, caption):
    """Pushes the video to the authorized account's TikTok inbox as a draft, for the creator to review
    and post from the TikTok app. Needs TIKTOK_CLIENT_KEY/SECRET/REFRESH_TOKEN (after app review passes)
    and the stoic-media domain verified in the TikTok app (Content Posting API -> Verify domains) so
    TikTok is allowed to pull video_url."""
    token = _tiktok_access_token()
    r = requests.post(f"{TIKTOK_API}/post/publish/inbox/video/init/",
                       headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                       json={"source_info": {"source": "PULL_FROM_URL", "video_url": _public_url(path)}})
    data = r.json()
    if data.get("error", {}).get("code") not in (None, "ok"): raise RuntimeError(data)
    return data.get("data", {}).get("publish_id")


def _notify_ntfy_tiktok(path, caption):
    """TikTok's app review hasn't passed yet, so we can't post automatically. Instead, ping a private
    ntfy.sh topic with today's video link and caption so it can be posted by hand from the TikTok app."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic: raise NotConnected("TikTok not connected yet, and NTFY_TOPIC isn't set for manual-post pings")
    url = _public_url(path)
    r = requests.post(f"https://ntfy.sh/{topic}", data=caption.encode("utf-8"), headers={
        "Title": "Unshaken: post this on TikTok".encode("utf-8"),
        "Click": url, "Attach": url, "Tags": "tiktok,memo",
    })
    r.raise_for_status()
    return {"ntfy_topic": topic, "media_url": url}


def publish_tiktok(path, caption):
    if os.environ.get("TIKTOK_REFRESH_TOKEN"):
        return _publish_tiktok_real(path, caption)
    return _notify_ntfy_tiktok(path, caption)


# ---------------- YouTube ----------------
YT_UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"


def _yt_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
    })
    data = r.json()
    if "access_token" not in data: raise RuntimeError(data)
    return data["access_token"]


def publish_youtube_short(path, caption):
    """Uploads path as a public video on the authorized channel (YT_CHANNEL_ID is the account the
    refresh token already belongs to; the API has no separate "post as channel X" switch, so this
    secret is just for our own bookkeeping/sanity-check, not sent in the request). Tagging the title
    #Shorts plus a vertical <=60s video is what gets it treated as a Short."""
    _need("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "YT_CHANNEL_ID")
    token = _yt_access_token()
    title = ((caption.splitlines()[0] if caption else "Unshaken").strip()[:95] + " #Shorts")
    metadata = {
        "snippet": {"title": title, "description": caption, "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    boundary = "unshaken_upload_boundary"
    with open(path, "rb") as f:
        video_bytes = f.read()
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode("utf-8") + video_bytes + f"\r\n--{boundary}--".encode("utf-8")
    r = requests.post(YT_UPLOAD_API, params={"uploadType": "multipart", "part": "snippet,status"},
                       headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/related; boundary={boundary}"},
                       data=body)
    return _check(r)["id"]

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
