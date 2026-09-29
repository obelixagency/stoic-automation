"""Turns one day's plan (plan_<date>.json, from run_day.py) into actual files: one reel (mp4) per item that
needs a video platform, one 4:5 post image and/or one 9:16 story image per item that needs those. Skips
anything already rendered, so re-running (the watchdog calls this every 30 min) costs nothing once done.
Uses real voice + word timings from audio/clips + audio/timings when they exist for an item; otherwise
falls back to estimated timing (silent) - so a reel upgrades automatically once that item's audio lands.
Usage: python render_day.py --date 2026-10-06"""
import argparse, glob, hashlib, json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import render as R

VIDEO_PLATFORMS = {"tiktok", "youtube_short", "instagram_reel", "facebook_reel"}
POST_PLATFORMS = {"instagram_post", "facebook_post"}
STORY_PLATFORMS = {"instagram_story", "facebook_story"}

def load_items():
    items = {}
    for f in glob.glob(os.path.join(HERE, "library", "library_*.json")):
        for i in json.load(open(f))["items"]: items[i["id"]] = i
    return items

def audio_for(item_id):
    tpath = os.path.join(HERE, "audio", "timings", item_id + ".json")
    cpath = os.path.join(HERE, "audio", "clips", item_id + ".m4a")
    if os.path.exists(tpath) and os.path.exists(cpath):
        return json.load(open(tpath))["times"], cpath
    return None, None

def pick_hook(item, rng):
    ok = [h for h in R.KIT["hooks"] if ("authors" not in h or item["author"] in h["authors"])
          and ("themes" not in h or set(h["themes"]) & set(item.get("themes", [])))]
    return rng.choice(ok or R.KIT["hooks"])["text"]

def seed_for(item_id): return int(hashlib.sha1(item_id.encode()).hexdigest(), 16) % 10_000

def render_item(item, formats, outdir, rng, music_path):
    made = []; sd = seed_for(item["id"])
    if VIDEO_PLATFORMS & set(formats):
        out = os.path.join(outdir, item["id"] + ".mp4")
        if not os.path.exists(out):
            times, clip = audio_for(item["id"])
            R.build_reel(item, out, hook=pick_hook(item, rng), timings=times, audio=clip, music=music_path, seed=sd)
        made.append(out)
    if POST_PLATFORMS & set(formats):
        out = os.path.join(outdir, item["id"] + "_post.jpg")
        if not os.path.exists(out): R.render_still(item, "post", out, seed=sd)
        made.append(out)
    if STORY_PLATFORMS & set(formats):
        out = os.path.join(outdir, item["id"] + "_story.jpg")
        if not os.path.exists(out): R.render_still(item, "story", out, seed=sd)
        made.append(out)
    return made

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--date", required=True); a = ap.parse_args()
    plan_path = os.path.join(HERE, f"plan_{a.date}.json")
    if not os.path.exists(plan_path):
        print("no plan yet for", a.date, "- run_day.py must run first"); return
    plan = json.load(open(plan_path)); items = load_items()
    outdir = os.path.join(HERE, "rendered"); os.makedirs(outdir, exist_ok=True)
    music_files = sorted(glob.glob(os.path.join(HERE, "music", "*.m4a")))
    rng = random.Random(a.date)
    for post in plan["posts"]:
        item = items[post["item_id"]]
        music = rng.choice(music_files) if music_files else None
        made = render_item(item, post["formats"], outdir, rng, music)
        print(post["slot"], post["item_id"], "->", [os.path.basename(m) for m in made])

if __name__ == "__main__": main()
