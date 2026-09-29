"""The monitor from the automation doc: "checks every half hour that every scheduled slot went out,
and retries whatever is late." Runs every 30 min via .github/workflows/watchdog.yml (cron is always UTC;
slot times are computed in America/New_York with zoneinfo, so this needs no manual DST edits, ever).

For each of today's slots (schedule.json), once its time has passed:
  - if it already has a successful publish for every platform in the plan -> nothing to do.
  - otherwise attempt to publish whatever is missing (this IS the "backup run": the doc's fixed
    +30min/+90min offsets are just "the watchdog runs every 30 min and retries until it works or is stale").
  - if the slot is more than STALE_HOURS past its scheduled time and still not fully posted -> ESCALATE
    (nonzero exit so GitHub Actions marks the run failed and emails/Slack-notifies whoever owns the repo).
"""
import argparse, datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import publish as PUB

ET = ZoneInfo("America/New_York")
LOG = os.path.join(HERE, "publish_log.json")
STALE_HOURS = 2.5          # matches the doc: "makes sure nothing has posted successfully in the last 2h" (+ margin)
RETRY_COOLDOWN_MIN = 25    # don't hammer a broken platform every single 30-min tick

def load_json(p, default): return json.load(open(p)) if os.path.exists(p) else default
def save_json(p, d): json.dump(d, open(p, "w"), indent=1, ensure_ascii=False)

def slot_time_utc(date_str, time_et):
    h, m = map(int, time_et.split(":"))
    local = dt.datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=ET)
    return local.astimezone(dt.timezone.utc)

def render_files(item_id, plan_post):
    """Where the scheduler job (render.yml, not shown here) is expected to have written this slot's files."""
    base = os.path.join(HERE, "rendered", plan_post["date"] if "date" in plan_post else "", item_id)
    out = {}
    if os.path.exists(base + ".mp4"): out["video"] = base + ".mp4"
    if os.path.exists(base + ".jpg"): out["image"] = base + ".jpg"
    return out

def run(date_str, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    schedule = json.load(open(os.path.join(HERE, "schedule.json")))
    log = load_json(LOG, {})                       # log[date][slot][platform] = {status, detail, attempts, last_attempt}
    log.setdefault(date_str, {})
    plan_path = os.path.join(HERE, f"plan_{date_str}.json")
    if not os.path.exists(plan_path):
        print(f"no plan for {date_str} yet (the scheduler job runs before any slot's time) - nothing to check")
        return 0
    plan = json.load(open(plan_path))
    escalations = []
    for post in plan["posts"]:
        slot_id = post["slot"]; cfg = next((s for s in schedule["slots"] if s["id"] == slot_id.replace("_static", "")), None)
        if not cfg: continue
        due = slot_time_utc(date_str, cfg["time_et"])
        if now < due: continue                                       # not time yet
        row = log[date_str].setdefault(slot_id, {})
        files = render_files(post["item_id"], {"date": date_str})
        for platform in post["formats"]:
            st = row.get(platform, {"status": "pending", "attempts": 0})
            if st["status"] == "ok": continue
            last = st.get("last_attempt")
            if last and (now - dt.datetime.fromisoformat(last)).total_seconds() < RETRY_COOLDOWN_MIN * 60: continue
            if "video" not in files and "image" not in files:
                st.update(status="waiting_on_render", attempts=st["attempts"] + 1, last_attempt=now.isoformat())
                row[platform] = st; continue
            caption = post.get("caption") or ""
            ok, detail = PUB.publish(platform, post["item_id"], files, caption)
            st.update(status="ok" if ok else "failed", detail=detail, attempts=st["attempts"] + 1, last_attempt=now.isoformat())
            row[platform] = st
            print(f'{date_str} {slot_id} {platform}: {st["status"]}' + ("" if ok else f' ({detail.get("error")})'))
        log[date_str][slot_id] = row
        late_hours = (now - due).total_seconds() / 3600
        unresolved = [p for p, st in row.items() if st["status"] not in ("ok",)]
        if late_hours >= STALE_HOURS and unresolved:
            escalations.append({"slot": slot_id, "item": post["item_id"], "late_hours": round(late_hours, 1), "platforms": unresolved})
    save_json(LOG, log)
    if escalations:
        print("\nESCALATE - past the", STALE_HOURS, "hour grace window and still not posted:")
        for e in escalations: print(" ", e)
        return 1
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--date", default=str(dt.date.today()))
    a = ap.parse_args(); sys.exit(run(a.date))
