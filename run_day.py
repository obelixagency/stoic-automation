"""Daily entry point the GitHub Actions cron calls.
Phase 1 (first AUDIO_PHASE_1_DAYS days after launch): only Marcus Aurelius + Seneca letters 1-65 (confirmed LibriVox audio).
After that: the whole library, once the recorded batch (audio/record_script.md) has been aligned and committed.
Usage: python run_day.py --launch-date 2026-10-06 [--date 2026-10-06]"""
import argparse, datetime as dt, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "audio"))
import selector as S, coverage as C

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launch-date", required=True)
    ap.add_argument("--date", default=str(dt.date.today()))
    ap.add_argument("--libs", default=os.path.join(HERE, "library", "library_*.json"))
    ap.add_argument("--history", default=os.path.join(HERE, "history.json"))
    a = ap.parse_args()
    items = S.load_library(a.libs)
    launch = dt.date.fromisoformat(a.launch_date); today = dt.date.fromisoformat(a.date)
    day_n = (today - launch).days + 1
    in_phase1 = 0 < day_n <= S.AUDIO_PHASE_1_DAYS
    ready = C.audio_ready_ids(items) if in_phase1 else None
    sel = S.Selector(items, audio_ready_ids=ready)
    hist = json.load(open(a.history)) if os.path.exists(a.history) else []
    plan = sel.pick_day(a.date, hist, seed=0)
    hist += plan["history_rows"]; json.dump(hist, open(a.history, "w"), indent=1, ensure_ascii=False)
    plan["phase"] = "phase1_audio_only" if in_phase1 else "full_library"
    plan["day_n"] = day_n
    out = os.path.join(HERE, f"plan_{a.date}.json"); json.dump(plan, open(out, "w"), indent=2, ensure_ascii=False)
    print(f"day {day_n} ({plan['phase']}):")
    for p in plan["posts"]: print(" ", p["slot"], p["item_id"], p["type"], p["how"])
    return plan

if __name__ == "__main__": main()
