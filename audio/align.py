"""Locate a library item inside an ASR transcript (word list with timestamps) and return per-word timings.
Pure Python (difflib only) so it runs anywhere and can be unit-tested without audio."""
import re
from difflib import SequenceMatcher
from collections import Counter

def norm_token(w):
    w = w.lower().replace("\u2019", "'").replace("-", "")
    return re.sub(r"[^a-z0-9']", "", w)

def tokens(text):
    """display words (what is shown on screen) -> normalized tokens; keeps a 1:1 index with text.split()"""
    text = text.replace("\u2026", " ").replace("\u2014", " ")
    words = text.split()
    return words, [norm_token(w) for w in words]

def _same(a, b):
    if a == b: return True
    if not a or not b: return False
    if len(a) >= 5 and len(b) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8: return True
    return False

def locate(asr, item_tok, lo=0, hi=None):
    """asr: list of (token, start, end). Returns (start_idx, end_idx_exclusive) window likely holding the item, or None."""
    hi = len(asr) if hi is None else hi
    A = [t for t, _, _ in asr[lo:hi]]
    T = [t for t in item_tok if t]
    if not T: return None
    k = 3 if len(T) >= 6 else 2 if len(T) >= 3 else 1
    idx = {}
    for i in range(len(A) - k + 1): idx.setdefault(tuple(A[i:i + k]), []).append(i)
    votes = Counter()
    for j in range(len(T) - k + 1):
        for i in idx.get(tuple(T[j:j + k]), []): votes[(i - j) // 6] += 1     # bucket offsets (tolerates small drift)
    if not votes: return None
    best, _ = max(votes.items(), key=lambda kv: kv[1] + votes.get(kv[0] - 1, 0) * .5 + votes.get(kv[0] + 1, 0) * .5)
    center = best * 6
    a = max(0, center - 12); b = min(len(A), center + len(T) + 18)
    return lo + a, lo + b

def align(asr, words, toks, window):
    """Align item tokens against asr[window]. Returns dict(score, times[(start,end) per display word], start, end)."""
    a, b = window
    seg = asr[a:b]; A = [t for t, _, _ in seg]
    T = [t if t else "\u0000" for t in toks]
    # map with SequenceMatcher on token lists, then fuzzy-repair unmatched pairs
    sm = SequenceMatcher(None, A, T, autojunk=False)
    m = {}                                   # item index -> asr index (within seg)
    for blk in sm.get_matching_blocks():
        for n in range(blk.size): m[blk.b + n] = blk.a + n
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for n in range(i2 - i1):
                if _same(A[i1 + n], T[j1 + n]): m[j1 + n] = i1 + n
    matched = sorted(m)
    real = [j for j in range(len(T)) if toks[j]]
    score = len([j for j in real if j in m]) / max(1, len(real))
    if not matched: return dict(score=0.0, times=None, start=None, end=None)
    # per-word times: matched words use ASR times; gaps are interpolated
    times = [None] * len(T)
    for j in matched: _, s, e = seg[m[j]]; times[j] = [s, e]
    first, last = matched[0], matched[-1]
    for j in range(len(T)):
        if times[j] is not None: continue
        prev = max((p for p in matched if p < j), default=None); nxt = min((q for q in matched if q > j), default=None)
        if prev is None:                       # words before the first matched one: extrapolate backwards (~0.34 s/word)
            n = first - j; times[j] = [max(0.0, times[first][0] - 0.34 * n), max(0.0, times[first][0] - 0.34 * (n - 1))]; continue
        if nxt is None:                        # words after the last matched one: extrapolate forwards
            n = j - last; times[j] = [times[last][1] + 0.34 * (n - 1), times[last][1] + 0.34 * n]; continue
        gap = [g for g in range(prev + 1, nxt)]; s0, e1 = times[prev][1], times[nxt][0]
        step = (e1 - s0) / (len(gap) + 1) if e1 > s0 else 0
        n = gap.index(j) + 1; times[j] = [s0 + step * (n - 1) if e1 > s0 else s0, s0 + step * n if e1 > s0 else s0]
    # enforce monotonic, non-overlapping
    out = []; t_prev = times[0][0]
    for s, e in times:
        s = max(s, t_prev); e = max(e, s + 0.05); out.append((round(s, 3), round(e, 3))); t_prev = e
    return dict(score=round(score, 3), times=out, start=out[0][0], end=out[-1][1])

def match_item(asr, item, lo=0, hi=None, min_score=0.85, review_score=0.75):
    """item: library dict. Returns dict(status, score, start, end, times, words)."""
    text = item.get("display_text") or item["text"]
    words, toks = tokens(text)
    win = locate(asr, toks, lo, hi)
    if not win: return dict(status="not_found", score=0.0)
    r = align(asr, words, toks, win)
    if r["times"] is None: return dict(status="not_found", score=0.0)
    r["status"] = "matched" if r["score"] >= min_score else ("review" if r["score"] >= review_score else "low_score")
    r["words"] = words
    return r
