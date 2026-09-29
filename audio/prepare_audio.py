"""Audio pipeline: download LibriVox chapters -> transcribe (faster-whisper) -> match items -> cut+normalize clips + word timings.
  python prepare_audio.py plan
  python prepare_audio.py transcribe --source meditations --chapter 2
  python prepare_audio.py align --libs "../library/library_*.json"
Runs on GitHub Actions (needs network). `align` also works offline on cached files (used in tests)."""
import argparse, glob, json, os, re, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import align as AL
WORK = os.path.join(HERE, "work"); CLIPS = os.path.join(HERE, "clips"); TIMES = os.path.join(HERE, "timings")
CFG = json.load(open(os.path.join(HERE, "audio_sources.json")))["sources"]

def source_for(item):
    """-> (source_key, chapter_number) or (None, None)"""
    if item["author"] == "Marcus Aurelius":
        m = re.match(r"(\d+)\.", item["ref"]); return ("meditations", int(m.group(1))) if m else (None, None)
    if item.get("work") == "Moral Letters to Lucilius":
        m = re.search(r"Letter (\d+)", item["ref"])
        if m:
            n = int(m.group(1))
            return ("letters_vogel_vol1", n) if n <= 65 else ("letters_vogel_vol2_vol3", n)
    return (None, None)

def resolved():
    p = os.path.join(WORK, "resolved.json")
    return json.load(open(p)) if os.path.exists(p) else {}

def url_for(source, chapter):
    c = CFG[source]
    for book in resolved().get(source, []):                      # filled by `resolve` (LibriVox API)
        secs = book.get("sections", [])
        if secs and 0 <= chapter < len(secs): return secs[chapter]["url"]
    if not c.get("archive_identifier") or not c.get("file_pattern"): return None
    return f'https://archive.org/download/{c["archive_identifier"]}/' + c["file_pattern"].format(n=chapter)

def download(url, dest, tries=4):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 10_000: return dest
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stoic-automation/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f: f.write(r.read())
            return dest
        except Exception as e: print("download retry", k, e); time.sleep(3 * (k + 1))
    raise RuntimeError("download failed: " + url)

def mp3_path(source, chapter): return os.path.join(WORK, "dl", f"{source}_{chapter:02d}.mp3")
def asr_path(source, chapter): return os.path.join(WORK, "asr", f"{source}_{chapter:02d}.json")

def cmd_resolve(a):
    """Ask the LibriVox API for the projects named in audio_sources.json (needs network). Writes work/resolved.json."""
    import urllib.parse
    out = {}
    for key, c in CFG.items():
        titles = c.get("librivox_titles_to_search") or ([c["librivox_title"]] if c.get("librivox_title") else [])
        for t in titles:
            q = urllib.parse.urlencode({"title": "^" + t, "format": "json", "extended": 1})
            try: data = json.load(urllib.request.urlopen("https://librivox.org/api/feed/audiobooks/?" + q, timeout=60))
            except Exception as e: print("resolve failed", t, e); continue
            for b in data.get("books", []):
                out.setdefault(key, []).append({"title": b.get("title"), "id": b.get("id"), "iarchive": b.get("url_iarchive"),
                    "authors": [x.get("last_name") for x in b.get("authors", [])],
                    "sections": [{"n": i, "title": s.get("title"), "url": s.get("listen_url"),
                                  "reader": (s.get("readers") or [{}])[0].get("display_name")} for i, s in enumerate(b.get("sections", []))]})
    os.makedirs(WORK, exist_ok=True); json.dump(out, open(os.path.join(WORK, "resolved.json"), "w"), indent=1)
    for k, v in out.items(): print(k, [(b["title"], len(b["sections"])) for b in v])
    print("NOTE: check translator on each LibriVox page; the transcript match score is the final judge.")

def cmd_matrix(a):
    """print the unique (source, chapter) pairs that have a candidate recording, as JSON for the GitHub Actions matrix"""
    pairs = set()
    for it in load(a.libs):
        s, ch = source_for(it)
        if s and (CFG[s].get("archive_identifier") or resolved().get(s)) and url_for(s, ch): pairs.add((s, ch))
    print(json.dumps({"include": [{"source": s, "chapter": c} for s, c in sorted(pairs)]}))

def cmd_plan(a):
    items = load(a.libs); need = {}; have = {}
    for it in items:
        s, ch = source_for(it)
        (have if s and (CFG[s].get("archive_identifier") or resolved().get(s)) else need).setdefault(s or "no_source", []).append(it["id"])
    print("candidate audio:", {k: len(v) for k, v in have.items()}); print("needs another source:", {k: len(v) for k, v in need.items()})
    json.dump({"has_candidate": have, "needs_audio": need}, open(os.path.join(HERE, "audio_plan.json"), "w"), indent=1)

def cmd_transcribe(a):
    url = url_for(a.source, a.chapter); assert url, f"no archive_identifier for {a.source}"
    mp3 = download(url, mp3_path(a.source, a.chapter))
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(mp3, language="en", word_timestamps=True, beam_size=1, condition_on_previous_text=False)
    words = [(AL.norm_token(w.word), round(w.start, 3), round(w.end, 3)) for s in segs for w in s.words if AL.norm_token(w.word)]
    os.makedirs(os.path.dirname(asr_path(a.source, a.chapter)), exist_ok=True)
    json.dump(words, open(asr_path(a.source, a.chapter), "w")); print(a.source, a.chapter, len(words), "words", round(info.duration), "s")

def load(pattern):
    items = []
    for f in sorted(glob.glob(pattern)): items += json.load(open(f))["items"]
    return items

def cut(src, start, end, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s0 = max(0.0, start - 0.20); dur = (end + 0.30) - s0
    af = f"afade=t=in:d=0.05,afade=t=out:st={dur-0.15:.2f}:d=0.15,loudnorm=I=-16:TP=-1.5:LRA=11"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s0:.3f}", "-t", f"{dur:.3f}", "-i", src, "-af", af,
                    "-ar", "44100", "-ac", "1", "-c:a", "aac", "-b:a", "128k", out], check=True)
    return s0, dur

def cmd_align(a):
    items = load(a.libs); index = {}; cache = {}
    for it in items:
        s, ch = source_for(it)
        if not s or not os.path.exists(asr_path(s, ch)): index[it["id"]] = {"status": "no_audio_source" if not s else "not_transcribed"}; continue
        asr = cache.setdefault((s, ch), [tuple(x) for x in json.load(open(asr_path(s, ch)))])
        r = AL.match_item(asr, it, min_score=a.min_score)
        if r["status"] not in ("matched", "review"): index[it["id"]] = {"status": r["status"], "score": r.get("score")}; continue
        s0, dur = cut(mp3_path(s, ch), r["start"], r["end"], os.path.join(CLIPS, it["id"] + ".m4a"))
        rel = [[round(st - s0, 3), round(en - s0, 3)] for st, en in r["times"]]
        os.makedirs(TIMES, exist_ok=True)
        json.dump({"id": it["id"], "words": r["words"], "times": rel, "clip_seconds": round(dur, 3)}, open(os.path.join(TIMES, it["id"] + ".json"), "w"))
        index[it["id"]] = {"status": r["status"], "score": r["score"], "clip": f"clips/{it['id']}.m4a", "timings": f"timings/{it['id']}.json", "seconds": round(dur, 2), "source": s, "chapter": ch}
    json.dump(index, open(os.path.join(HERE, "audio_index.json"), "w"), indent=1)
    from collections import Counter; print(dict(Counter(v["status"] for v in index.values())))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "resolve", "matrix", "transcribe", "align"):
        p = sub.add_parser(name); p.add_argument("--libs", default=os.path.join(HERE, "..", "library", "library_*.json"))
        if name == "transcribe": p.add_argument("--source", required=True); p.add_argument("--chapter", type=int, required=True); p.add_argument("--model", default="small.en")
        if name == "align": p.add_argument("--min-score", type=float, default=0.85)
    a = ap.parse_args(); {"plan": cmd_plan, "resolve": cmd_resolve, "matrix": cmd_matrix, "transcribe": cmd_transcribe, "align": cmd_align}[a.cmd](a)
