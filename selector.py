"""Daily content selector. Picks what to post in each slot while enforcing the brand rules.
Usage: plan = pick_day("2026-10-01", history); history += plan["history_rows"]"""
import json, glob, os, re, random, datetime as dt
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = json.load(open(os.path.join(HERE, "kit.json")))
NO_REPEAT_DAYS = 90
AUDIO_PHASE_1_DAYS = 12          # while the human-recorded batch (Epictetus + Seneca dialogues, ~96 min) is being read;
                                  # after this many days pick_day() should be called with audio_ready_ids=None
RECYCLE_MIN_AGE = 45          # a recycled item must be at least this old, and is re-rendered with a new hook + background
HOOK_CTA_DAYS = 7
MORNING_THEMES = {"morning", "discipline", "purpose", "procrastination", "focus", "urgency"}
EVENING_THEMES = {"anxiety", "anger", "people", "time", "mortality", "adversity", "acceptance", "fear"}

def load_library(pattern):
    items = []
    for f in sorted(glob.glob(pattern)): items += json.load(open(f))["items"]
    ids = [i["id"] for i in items]; assert len(ids) == len(set(ids)), "duplicate ids"
    return items

# ---- overlap groups: quote + passage cut from the same lines count as the same content ----
def _norm(t): return re.findall(r"[a-z']+", t.lower().replace("\u2019", "'"))
def group_items(items):
    W = {i["id"]: _norm(i["text"]) for i in items}
    S = {k: {" ".join(w[j:j + 7]) for j in range(max(1, len(w) - 6))} for k, w in W.items()}
    J = {k: " ".join(w) for k, w in W.items()}
    parent = {i["id"]: i["id"] for i in items}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    ids = list(W)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            x, y = ids[a], ids[b]
            shared = S[x] & S[y] if len(W[x]) >= 7 and len(W[y]) >= 7 else set()
            short, long_ = (x, y) if len(W[x]) <= len(W[y]) else (y, x)
            contained = len(W[short]) >= 4 and J[short] in J[long_]
            if shared or contained: parent[find(x)] = find(y)
    return {k: find(k) for k in ids}

class Selector:
    def __init__(self, items, audio_ready_ids=None):
        """audio_ready_ids: optional set of item ids whose voice recording is confirmed to exist (see audio/coverage.py).
        Phase 1 (while the recorded batch for the rest is still pending) posts ONLY audio-ready items, so every
        reel goes out with a real voice instead of estimated timing. Pass None to disable phasing (post everything)."""
        self.audio_ready = audio_ready_ids
        self.items = {i["id"]: i for i in items}; self.group = group_items(items)
        by = lambda t: [i for i in items if i["type"] == t]
        self.quotes, self.passages, self.stories = by("quote_reel"), by("passage_reel"), by("story_reel")

    # ---------- eligibility ----------
    def _last_used(self, history, today):
        last = {}
        for h in history:
            d = dt.date.fromisoformat(h["date"])
            if d <= today: last[h["group"]] = max(last.get(h["group"], d), d)
        return last

    def _ok_author(self, cand, seq):
        return not (len(seq) >= 2 and seq[-1] == seq[-2] == cand["author"])

    def _candidates(self, pool, today, last, used_today, seq, slot):
        out = []
        for i in pool:
            g = self.group[i["id"]]
            if g in used_today: continue
            if i.get("sensitivity") and slot not in ("evening",): continue
            if self.audio_ready is not None and i["id"] not in self.audio_ready: continue
            lu = last.get(g)
            if lu and (today - lu).days < NO_REPEAT_DAYS: continue
            out.append(i)
        return out

    def _score(self, i, slot, rng, seq):
        s = rng.random() * 0.5
        th = set(i.get("themes", []))
        if slot == "morning" and th & MORNING_THEMES: s += 2
        if slot == "evening" and th & EVENING_THEMES: s += 1.5
        s += 0.4 * (3 - Counter(seq[-6:])[i["author"]] if len(seq) else 0) / 3   # nudge toward the least-used author
        return s

    def _choose(self, pools, slot, today, history, used_today, seq, rng, filt=lambda i: True):
        last = self._last_used(history, today); relaxed = []
        for label, pool in pools:
            c = self._candidates([x for x in pool if filt(x)], today, last, used_today, seq, slot)
            ok = [i for i in c if self._ok_author(i, seq)]
            if ok: return max(ok, key=lambda i: self._score(i, slot, rng, seq)), label
            if c: relaxed.append((label, c))
        # recycle: least-recently-used content that is at least RECYCLE_MIN_AGE days old (author rule still respected)
        old = []
        for _, p in pools:
            for i in p:
                if not filt(i): continue
                if self.audio_ready is not None and i["id"] not in self.audio_ready: continue
                g = self.group[i["id"]]
                if g in used_today or (i.get("sensitivity") and slot != "evening"): continue
                lu = last.get(g); age = (today - lu).days if lu else 9999
                if RECYCLE_MIN_AGE <= age < NO_REPEAT_DAYS: old.append((age, i))
        okold = [(a, i) for a, i in old if self._ok_author(i, seq)]
        if okold: return max(okold, key=lambda t: (t[0], rng.random()))[1], "recycled"
        if relaxed:
            label, c = relaxed[0]; return max(c, key=lambda i: self._score(i, slot, rng, seq)), label + "+author_rule_relaxed"
        if old: return max(old, key=lambda t: (t[0], rng.random()))[1], "recycled+author_rule_relaxed"
        return None, "EXHAUSTED"

    # ---------- hooks / CTAs / captions ----------
    def _hook(self, item, history, today, rng):
        ok = []
        for h in KIT["hooks"]:
            if "authors" in h and item["author"] not in h["authors"]: continue
            if "themes" in h and not set(h["themes"]) & set(item.get("themes", [])): continue
            ok.append(h)
        recent = [x for x in history if x.get("hook_id")]
        last_hook = recent[-1]["hook_id"] if recent else None
        lu = {h["id"]: -1 for h in ok}
        for n, x in enumerate(recent):
            if x["hook_id"] in lu: lu[x["hook_id"]] = n
        cand = [h for h in ok if h["id"] != last_hook] or ok
        cand.sort(key=lambda h: (lu[h["id"]], rng.random()))
        return cand[0]

    def _cta(self, item, hook, history, today, rng):
        ctas = KIT["ctas"]
        if item.get("sensitivity"): ctas = [c for c in ctas if c["id"] in ("c02", "c03")]
        used = {(x["hook_id"], x["cta_id"]) for x in history
                if x.get("hook_id") and (today - dt.date.fromisoformat(x["date"])).days < HOOK_CTA_DAYS}
        ok = [c for c in ctas if (hook["id"], c["id"]) not in used] or ctas
        lu = {c["id"]: -1 for c in ok}
        for n, x in enumerate(history):
            if x.get("cta_id") in lu: lu[x["cta_id"]] = n
        ok.sort(key=lambda c: (lu[c["id"]], rng.random())); return ok[0]

    def _caption(self, item, hook, cta, rng):
        tags = KIT["hashtags"]; a = tags["by_author"].get(item["author"], [])
        chosen = tags["core"][:2] + a + rng.sample(tags["broad"], 3)
        credit = item.get("display_credit") or f'{item["author"]}, {item["ref"]}'
        words = (item.get("display_text") or item["text"]).split()
        body = f"\u201c{item.get('display_text') or item['text']}\u201d\n\u2014 {credit}" if len(words) <= 45 else f"\u2014 {credit}\nFull passage in the video."
        return f'{hook["text"]}\n\n{body}\n\n{cta["text"]}\n\n{" ".join(chosen)}'

    # ---------- the day ----------
    def phase_active(self):
        return self.audio_ready is not None

    def pick_day(self, date, history, seed=0):
        today = dt.date.fromisoformat(date); rng = random.Random(f"{date}-{seed}")
        used_today, seq, picks = set(), [h["author"] for h in history[-3:]], []
        def add(slot, item, how, video, fmts):
            hk = self._hook(item, history + [p["row"] for p in picks], today, rng) if video else None
            ct = self._cta(item, hk, history + [p["row"] for p in picks], today, rng) if video else None
            row = dict(date=date, slot=slot, item_id=item["id"], group=self.group[item["id"]], author=item["author"],
                       hook_id=hk["id"] if hk else None, cta_id=ct["id"] if ct else None, how=how)
            picks.append(dict(slot=slot, item_id=item["id"], type=item["type"], how=how, formats=fmts,
                              recycled=(how == "recycled"), hook=hk["text"] if hk else None,
                              caption=self._caption(item, hk, ct, rng) if video else None, row=row))
            used_today.add(self.group[item["id"]]); seq.append(item["author"])
        H = lambda: history + [p["row"] for p in picks]
        it, how = self._choose([("quote", self.quotes)], "morning", today, H(), used_today, seq, rng, lambda i: i["est_seconds"] <= 30)
        if it: add("morning", it, how, True, ["tiktok", "youtube_short", "instagram_reel", "facebook_reel"])
        it, how = self._choose([("story", self.stories), ("quote", self.quotes)], "midday", today, H(), used_today, seq, rng, lambda i: i["est_seconds"] <= 100)
        if it: add("midday", it, how, True, ["tiktok", "youtube_short"])
        it, how = self._choose([("quote", self.quotes)], "midday_static", today, H(), used_today, seq, rng, lambda i: len((i.get("display_text") or i["text"]).split()) <= 40)
        if it: add("midday_static", it, how, False, ["instagram_post", "instagram_story", "facebook_post", "facebook_story"])
        it, how = self._choose([("passage", self.passages), ("long_quote", [q for q in self.quotes if q["est_seconds"] >= 14]), ("story", self.stories)],
                               "evening", today, H(), used_today, seq, rng)
        if it: add("evening", it, how, True, ["tiktok", "youtube_short", "instagram_reel", "facebook_reel"])
        return dict(date=date, posts=[{k: v for k, v in p.items() if k != "row"} for p in picks], history_rows=[p["row"] for p in picks])

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Plan one day of posts")
    ap.add_argument("--date", default=str(dt.date.today())); ap.add_argument("--lib", default="library/library_*.json")
    ap.add_argument("--history", default="history.json"); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    hist = json.load(open(a.history)) if os.path.exists(a.history) else []
    sel = Selector(load_library(a.lib)); plan = sel.pick_day(a.date, hist)
    hist += plan["history_rows"]; json.dump(hist, open(a.history, "w"), indent=1)
    out = a.out or f"plan_{a.date}.json"; json.dump(plan, open(out, "w"), indent=2, ensure_ascii=False)
    for p in plan["posts"]: print(p["slot"], p["item_id"], p["how"])
