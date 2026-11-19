"""Per-platform, per-slot performance numbers for the reels we publish. Runs at the start of every watchdog run.

Public-repo rule (SECURITY_OUTPUTS.md): only NUMBERS are stored - never media/post IDs, captions or provider
text. Published videos are matched to (date, slot, platform) from publish_log.json by caption hook and time.

Each entry in insights_log.json records `slot_utc`, `slot_local` (America/New_York via zoneinfo, so DST is
handled, never hand-edited), `slot_cairo`, and `scored_on` (when numbers were last read). Videos that were
published earlier get stats retroactively; nothing older than MAX_AGE_DAYS is ever fetched, and an entry is
re-read until it is FREEZE_DAYS old (numbers keep growing for a few days), then frozen.
"""
import datetime as dt, json, os, statistics, sys
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import meta_api as M
import watchdog as W

ET, CAIRO = ZoneInfo("America/New_York"), ZoneInfo("Africa/Cairo")
INSIGHTS = os.path.join(HERE, "insights_log.json")
REPORT = os.path.join(HERE, "INSIGHTS_REPORT.md")
MAX_AGE_DAYS = 60
FREEZE_DAYS = 7
MATCH_BEFORE_MIN, MATCH_AFTER_MIN = 5, 45   # media timestamp vs. the log's attempt time
PLATFORMS = {"instagram_reel": "ig", "facebook_reel": "fb"}


def _first_line(text):
    return (text or "").strip().split("\n")[0].strip()


def _parse(ts):
    # Graph timestamps look like 2026-11-18T19:19:02+0000
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def published_items(log, today, now):
    """Every ok reel publication in range -> list of dicts (no IDs)."""
    out = []
    for date_str in sorted(log):
        d = dt.date.fromisoformat(date_str)
        if (today - d).days > MAX_AGE_DAYS:
            continue
        plan_path = os.path.join(HERE, f"plan_{date_str}.json")
        if not os.path.exists(plan_path):
            continue
        plan = json.load(open(plan_path))
        schedule = json.load(open(os.path.join(HERE, "schedule.json")))
        for post in plan["posts"]:
            slot = post["slot"]
            cfg = next((s for s in schedule["slots"] if s["id"] == slot.replace("_static", "")), None)
            if not cfg:
                continue
            for platform in PLATFORMS:
                st = log[date_str].get(slot, {}).get(platform)
                if not st or st.get("status") != "ok":
                    continue
                slot_utc = W.slot_time_utc(date_str, cfg["time_et"])
                out.append({"date": date_str, "slot": slot, "platform": platform, "type": post.get("type"),
                            "hook": _first_line(post.get("caption")), "slot_utc": slot_utc,
                            "attempt": dt.datetime.fromisoformat(st["last_attempt"])})
    return out


def match(item, media, used):
    """Nearest unused media with the same hook, created shortly after the publish attempt."""
    best = None
    for m in media:
        if m["id"] in used or _first_line(m.get("text")) != item["hook"]:
            continue
        delta = (m["time"] - item["attempt"]).total_seconds() / 60
        if -MATCH_BEFORE_MIN <= delta <= MATCH_AFTER_MIN and (best is None or abs(delta) < best[0]):
            best = (abs(delta), m)
    return best[1] if best else None


def _fetch(platform, page_id, ig_id, token):
    if platform == "instagram_reel":
        ok, d = M.get(f"{ig_id}/media", token, fields="id,timestamp,caption,media_product_type", limit=100)
        if not ok:
            return None, d
        return [{"id": m["id"], "time": _parse(m["timestamp"]), "text": m.get("caption")}
                for m in d.get("data", []) if m.get("media_product_type") == "REELS"], None
    ok, d = M.get(f"{page_id}/video_reels", token, fields="id,created_time,description", limit=100)
    if not ok:
        return None, d
    return [{"id": m["id"], "time": _parse(m["created_time"]), "text": m.get("description")}
            for m in d.get("data", [])], None


def _numbers(platform, media_id, token):
    if platform == "instagram_reel":
        ok, s = M.ig_media_stats(media_id, token)
        if not ok:
            return None, s
        return {"views": s.get("views"), "reach": s.get("reach"), "saves": s.get("saved"),
                "shares": s.get("shares"), "likes": s.get("likes"), "comments": s.get("comments")}, None
    ok, s = M.fb_reel_stats(media_id, token)
    if not ok:
        return None, s
    return {"views": s.get("blue_reels_play_count"), "avg_watch_ms": s.get("post_video_avg_time_watched")}, None


def collect(now=None, token=None, page_id=None, ig_id=None):
    """Update insights_log.json. Returns a list of one-line notes (platform + short code, no secrets)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    notes = []
    page_id = page_id or os.environ.get("FB_PAGE_ID"); ig_id = ig_id or os.environ.get("IG_USER_ID")
    token = token or M.page_token(page_id=page_id)
    if not token:
        return ["analytics: skipped (no usable Meta token)"]
    store = W.load_json(INSIGHTS, {"entries": {}})
    items = published_items(W.load_json(W.LOG, {}), now.date(), now)
    for platform in PLATFORMS:
        mine = [i for i in items if i["platform"] == platform]
        todo = []
        for i in mine:
            key = f'{i["date"]}|{i["slot"]}|{platform}'
            e = store["entries"].get(key)
            age_days = (now - i["slot_utc"]).total_seconds() / 86400
            if e and e.get("scored_on") and age_days > FREEZE_DAYS and e.get("frozen"):
                continue
            if age_days < 0.04:    # first ~hour: nothing meaningful yet
                continue
            todo.append(i)
        if not todo:
            continue
        media, err = _fetch(platform, page_id, ig_id, token)
        if media is None:
            notes.append(f"analytics: {platform} media list failed ({err})"); continue
        used, failed = set(), 0
        for i in todo:
            m = match(i, media, used)
            if not m:
                notes.append(f'analytics: {platform} {i["date"]} {i["slot"]} no matching media'); continue
            used.add(m["id"])
            nums, err = _numbers(platform, m["id"], token)
            if nums is None:
                failed += 1; last_err = err; continue
            age_days = (now - i["slot_utc"]).total_seconds() / 86400
            store["entries"][f'{i["date"]}|{i["slot"]}|{platform}'] = {
                "date": i["date"], "slot": i["slot"], "platform": platform, "type": i["type"],
                "slot_utc": i["slot_utc"].isoformat(),
                "slot_local": i["slot_utc"].astimezone(ET).strftime("%Y-%m-%d %H:%M %Z"),
                "slot_cairo": i["slot_utc"].astimezone(CAIRO).strftime("%Y-%m-%d %H:%M"),
                "scored_on": now.isoformat(), "frozen": age_days > FREEZE_DAYS, **nums}
        if failed:
            notes.append(f"analytics: {platform} insights failed for {failed} video(s) ({last_err})")
    W.save_json(INSIGHTS, store)
    return notes


MIN_AGE_DAYS = 3   # numbers younger than this are still growing; slots are compared at maturity only


def _mature(e):
    try:
        age = (dt.datetime.fromisoformat(e["scored_on"]) - dt.datetime.fromisoformat(e["slot_utc"])).total_seconds() / 86400
    except Exception:
        return False
    return age >= MIN_AGE_DAYS


def build_report(store):
    rows = {}
    store = {"entries": {k: e for k, e in store.get("entries", {}).items() if _mature(e)}}
    for e in store.get("entries", {}).values():
        if e.get("views") is None:
            continue
        rows.setdefault((e["platform"], e["slot"]), []).append(e)
    lines = ["# Reach by platform and slot", "",
             "Auto-generated every watchdog run. Only videos at least 3 days old are counted. Views = IG `views` / FB `blue_reels_play_count`. Slot times are US Eastern (audience time).", "",
             "| Platform | Slot | Videos | Median views | Mean views | Total views |", "|---|---|---|---|---|---|"]
    for (platform, slot), es in sorted(rows.items()):
        v = [x["views"] for x in es]
        lines.append(f"| {platform} | {slot} | {len(v)} | {statistics.median(v):.0f} | {statistics.mean(v):.0f} | {sum(v):.0f} |")
    types = {}
    for e in store.get("entries", {}).values():
        if e.get("views") is not None:
            types.setdefault((e["platform"], e.get("type")), []).append(e["views"])
    lines += ["", "## By content type (median views, per platform)", ""]
    for (pl, t), v in sorted(types.items(), key=lambda kv: -statistics.median(kv[1])):
        lines.append(f"- {pl} / {t}: {statistics.median(v):.0f} ({len(v)} videos)")
    return "\n".join(lines) + "\n"


def main():
    notes = collect()
    for n in notes:
        print(n)
    with open(REPORT, "w") as f:
        f.write(build_report(W.load_json(INSIGHTS, {"entries": {}})))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("analytics: internal error (details withheld)")
        sys.exit(0)
