"""Visual template renderer: quote -> 1080x1920 reel (word-by-word), 4:5 post, 9:16 story.
Pure Pillow + numpy + ffmpeg. No network needed (background is procedural; production swaps in a Pexels photo)."""
import json, os, re, subprocess, functools, shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = json.load(open(os.path.join(HERE, "brand.json")))
KIT = json.load(open(os.path.join(HERE, "kit.json")))
def _rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
IVORY, BRONZE, BRONZE_L, BGC = (_rgb(BRAND["colors"][k]) for k in ("ivory", "bronze", "bronze_light", "bg"))

def _fontpath(name):
    for d in BRAND["fonts"]["search_dirs"]:
        p = os.path.join(HERE if d.startswith("./") else "", d, name) if d.startswith("./") else os.path.join(d, name)
        if os.path.exists(p): return p
    raise FileNotFoundError(name)

@functools.lru_cache(maxsize=None)
def F(kind, size, weight=None):
    f = ImageFont.truetype(_fontpath(BRAND["fonts"][kind]), size)
    if weight is not None:
        try: f.set_variation_by_axes([weight])
        except Exception: pass
    return f

# ---------- background ----------
def _noise(rng, w, h, scale):
    a = rng.random((h // scale + 3, w // scale + 3)).astype(np.float32)
    im = Image.fromarray((a * 255).astype(np.uint8)).resize((w + scale * 2, h + scale * 2), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32)[:h, :w] / 255

def make_bg(w, h, seed=1):
    rng = np.random.default_rng(seed)
    n = .50 * _noise(rng, w, h, 420) + .30 * _noise(rng, w, h, 160) + .14 * _noise(rng, w, h, 54) + .06 * _noise(rng, w, h, 14)
    n = (n - n.min()) / (n.max() - n.min())
    ridge = 1 - np.abs(2 * _noise(rng, w, h, 380) - 1)
    ridge = np.clip((ridge - .945) / .055, 0, 1) ** 1.5
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w * .5) / (w * .75)) ** 2 + ((yy - h * .40) / (h * .62)) ** 2)
    img = 16 + n * 20 + np.clip(1 - d, 0, 1) ** 1.6 * 16 + ridge * 8
    img = img * np.clip(1 - (d - .55) * .9, .55, 1) + rng.normal(0, 1.5, (h, w)).astype(np.float32)
    rgb = np.stack([img, img * .985, img * .95], -1)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

# ---------- text layout ----------
def _wrap(words, f, width):
    sp = f.getlength(" "); lines, cur, cw = [], [], 0
    for i, w in enumerate(words):
        ww = f.getlength(w)
        if cur and cw + sp + ww > width: lines.append(cur); cur, cw = [i], ww
        else: cw = ww if not cur else cw + sp + ww; cur.append(i)
    if cur: lines.append(cur)
    return lines

def _balanced(words, f, width):
    n = len(_wrap(words, f, width)); lo, hi = width * .5, width
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(_wrap(words, f, mid)) <= n: hi = mid
        else: lo = mid
    return _wrap(words, f, hi)

def fit(words, kind, weight, width, height, max_size, min_size, lh=1.3):
    for size in range(max_size, min_size - 1, -2):
        f = F(kind, size, weight); lines = _balanced(words, f, width)
        if len(lines) * size * lh <= height: return f, size, lines, True
    f = F(kind, min_size, weight); return f, min_size, _balanced(words, f, width), False

def place(words, f, size, lines, cx, top, lh=1.3):
    sp = f.getlength(" "); pos = {}; y = top
    for line in lines:
        ws = [f.getlength(words[i]) for i in line]; x = cx - (sum(ws) + sp * (len(line) - 1)) / 2
        for i, wd in zip(line, ws): pos[i] = (x, y); x += wd + sp
        y += size * lh
    return pos, len(lines) * size * lh

def paginate(words, width, height, min_size=58):
    pages, i = [], 0
    while i < len(words):
        rem = len(words) - i; lo, hi = 1, rem
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fit(words[i:i + mid], "quote", 500, width, height, min_size, min_size)[3]: lo = mid
            else: hi = mid - 1
        n = lo
        if i + n < len(words):
            for pat in (r"[.?!;:]$", r"[,\u2014]$"):
                j = next((j for j in range(n, int(n * .6), -1) if re.search(pat, words[i + j - 1])), None)
                if j: n = j; break
            left = len(words) - i - n
            if 0 < left < 10: n = max(int(n * .6), n - (10 - left))
        pages.append(words[i:i + n]); i += n
    return pages

# ---------- chrome ----------
def spaced(d, cx, y, text, f, fill, sp):
    tw = sum(f.getlength(c) for c in text) + sp * (len(text) - 1); x = cx - tw / 2
    for c in text: d.text((x, y), c, font=f, fill=fill, anchor="ls"); x += f.getlength(c) + sp

def split_credit(item):
    cr = item.get("display_credit") or f'{item["author"]}, {item["ref"]}'
    a = item["author"]; src = cr[len(a) + 2:] if cr.startswith(a + ", ") else cr
    return a.upper(), src

def chrome(W, H, fmt, credit=None, glyph_y=None):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay); cx = W // 2; c = BRAND["formats"][fmt]
    spaced(d, cx, c["brand_y"], BRAND["name"], F("sans_med", 30), BRONZE + (255,), 9)
    d.line([(cx - 40, c["brand_y"] + 26), (cx + 40, c["brand_y"] + 26)], fill=BRONZE + (200,), width=2)
    if glyph_y is not None:
        d.text((cx, glyph_y), "\u201c", font=F("quote", 200, 500), fill=BRONZE + (70,), anchor="mm")
    if credit:
        a, src, y = credit
        d.line([(cx - 45, y), (cx + 45, y)], fill=BRONZE + (255,), width=2)
        spaced(d, cx, y + 58, a, F("sans_med", 31), BRONZE_L + (255,), 6)
        f = F("sans_light", 27); tw = f.getlength(src)
        d.text((cx - tw / 2, y + 106), src, font=f, fill=IVORY + (175,), anchor="ls")
    if fmt == "post":
        f = F("sans_light", 25); h = BRAND["handle"]
        d.text((cx - f.getlength(h) / 2, H - 70), h, font=f, fill=IVORY + (120,), anchor="ls")
    return lay

CREDIT_H = 150

# ---------- pages ----------
def make_page(text, fmt, item=None, kind="quote", weight=500, max_size=None, hook=False):
    c = BRAND["formats"][fmt]; W, H = c["w"], c["h"]
    ztop, zbot = c["zone_top"], c["zone_bottom"]; words = text.split()
    credit_h = 0 if hook else CREDIT_H; gap = 0 if hook else 64
    f, size, lines, ok = fit(words, kind, weight, c["text_w"], zbot - ztop - credit_h - gap - 20, max_size or c["max_size"], c["min_size"])
    th = len(lines) * size * 1.3; total = th + gap + credit_h
    top = ztop + (zbot - ztop - total) / 2
    pos, _ = place(words, f, size, lines, W // 2, top)
    cy = top + th + gap
    a, src = split_credit(item) if (item and not hook) else (None, None)
    layer = chrome(W, H, fmt, (a, src, cy) if a else None, glyph_y=(top - 120) if (not hook and item and top - 120 > c["brand_y"] + 110) else None)
    return dict(words=words, pos=pos, f=f, size=size, fits=ok, W=W, H=H, chrome=layer, top=top)

def text_layer(pg, states, shadow_only=False):
    W, H = pg["W"], pg["H"]; lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    cols = {0: IVORY + (92,), 1: IVORY + (255,), 2: BRONZE_L + (255,)}
    for i, w in enumerate(pg["words"]):
        d.text(pg["pos"][i], w, font=pg["f"], fill=(0, 0, 0, 150) if shadow_only else cols[states[i]])
    return lay

def shadow_of(pg):
    lay = Image.new("RGBA", (pg["W"], pg["H"]), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for i, w in enumerate(pg["words"]): d.text((pg["pos"][i][0], pg["pos"][i][1] + 4), w, font=pg["f"], fill=(0, 0, 0, 150))
    return lay.filter(ImageFilter.GaussianBlur(8))

def compose(pg, states, shadow):
    return Image.alpha_composite(Image.alpha_composite(shadow, pg["chrome"]), text_layer(pg, states))

def smart(s):
    s = re.sub(r'(^|[\s(\[\u2014\u2026])"', "\\1\u201c", s).replace('"', "\u201d")
    s = re.sub(r"(^|[\s(\[\u2014\u201c\u2026])'", "\\1\u2018", s).replace("'", "\u2019")
    return s
def dtext(item): return smart(item.get("display_text") or item["text"])

def render_carousel(item, fmt, outdir, prefix, seed=3, max_slides=6):
    """Splits the item's text into pages (same paginate() used for passage reels) and renders each page as
    its own still (post 4:5 by default). Returns the list of file paths written, slide 1 first."""
    c = BRAND["formats"][fmt]; words = dtext(item).split()
    pages = paginate(words, c["text_w"], c["zone_bottom"] - c["zone_top"] - CREDIT_H - 84) if len(words) > 40 else [words]
    pages = pages[:max_slides]
    bg = make_bg(c["w"], c["h"], seed).convert("RGBA")
    out = []
    for i, pw in enumerate(pages, 1):
        pg = make_page(" ".join(pw), fmt, item, max_size=(c["max_size"] if len(pages) == 1 else 76))
        img = Image.alpha_composite(bg, compose(pg, [1] * len(pg["words"]), shadow_of(pg))).convert("RGB")
        path = f"{outdir}/{prefix}_carousel_{i}.jpg"; img.save(path, quality=95); out.append(path)
    return out

# ---------- stills ----------
def render_still(item, fmt, out, seed=3, text=None):
    c = BRAND["formats"][fmt]; bg = make_bg(c["w"], c["h"], seed).convert("RGBA")
    pg = make_page(text or dtext(item), fmt, item)
    img = Image.alpha_composite(bg, compose(pg, [1] * len(pg["words"]), shadow_of(pg))).convert("RGB")
    img.save(out, quality=95); return pg["fits"], pg["size"]

# ---------- timings & video ----------
def est_timings(words, wps=2.3):
    t, out = 0.0, []
    avg = np.mean([len(re.sub(r"\W", "", w)) or 1 for w in words])
    for w in words:
        L = len(re.sub(r"\W", "", w)) or 1; dur = (.6 + .4 * L / avg) / wps
        pause = .45 if re.search(r"[.?!]$", w) else (.22 if re.search(r"[,;:\u2014]$", w) else 0)
        out.append((t, t + dur)); t += dur + pause
    return out

def build_reel(item, out_mp4, hook=None, fmt="reel", seed=3, timings=None, audio=None, music=None, workdir="/tmp/reelwork"):
    """timings: per-word [start, end] RELATIVE TO THE CLIP (from audio/prepare_audio.py). audio: the voice clip. music: ambient bed.
    Without audio it falls back to estimated timing (silent or music only)."""
    c = BRAND["formats"][fmt]; W, H = c["w"], c["h"]; tm = BRAND["timing"]
    shutil.rmtree(workdir, ignore_errors=True); os.makedirs(workdir)
    make_bg(W, H, seed).save(f"{workdir}/bg.png")
    words = dtext(item).split(); voiced = bool(audio and timings)
    hook_s = tm["hook_seconds"] if hook else 0.0
    times = [tuple(t) for t in timings] if voiced else est_timings(words, tm["est_words_per_second"])
    assert len(times) == len(words), f"timings ({len(times)}) must match display words ({len(words)})"
    frames = []
    if hook:
        pg = make_page(smart(hook), fmt, None, kind="quote_italic", weight=500, max_size=80, hook=True)
        frames.append((compose(pg, [1] * len(pg["words"]), shadow_of(pg)), hook_s))
    pages = paginate(words, c["text_w"], c["zone_bottom"] - c["zone_top"] - CREDIT_H - 84) if len(words) > 40 else [words]
    built = []; k0 = 0
    for pw in pages:
        pg = make_page(" ".join(pw), fmt, item, max_size=(c["max_size"] if len(pages) == 1 else 76)); built.append((pg, shadow_of(pg), k0, len(pw))); k0 += len(pw)
    tail = 1.2 if voiced else tm["page_hold_seconds"]
    first_start = times[0][0]
    if voiced and first_start > 0.02:                                   # short pre-roll: page visible, nothing highlighted yet
        pg, sh, _, n = built[0]; frames.append((compose(pg, [0] * n, sh), first_start))
    for pi, (pg, sh, k0, n) in enumerate(built):
        for k in range(n):
            g = k0 + k; st = [1] * k + [2] + [0] * (n - k - 1)
            if g + 1 < len(times): dur = times[g + 1][0] - times[g][0]
            else: dur = times[g][1] - times[g][0]
            frames.append((compose(pg, st, sh), max(dur, .06)))
        if not voiced or pi == len(built) - 1:                        # with real audio there is no artificial page hold
            frames.append((compose(pg, [1] * n, sh), tail if pi == len(built) - 1 else tm["page_hold_seconds"]))
    lines = []
    for i, (im, dur) in enumerate(frames):
        p = f"{workdir}/f{i:04d}.png"; im.save(p); lines += [f"file '{p}'", f"duration {dur:.3f}"]
    lines.append(f"file '{workdir}/f{len(frames)-1:04d}.png'")
    open(f"{workdir}/list.txt", "w").write("\n".join(lines))
    total = sum(d for _, d in frames)
    zoom = "zoompan=z='min(1+0.00022*on,1.09)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=30" % (W, H)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", f"{workdir}/bg.png", "-f", "concat", "-safe", "0", "-i", f"{workdir}/list.txt"]
    ai = 2; fc = [f"[0:v]scale={int(W*1.4)}:{int(H*1.4)},{zoom}[bg]", "[1:v]fps=30,format=rgba[t]", "[bg][t]overlay=format=auto,fade=t=in:st=0:d=0.5,format=yuv420p[v]"]
    labels = []
    if audio:
        cmd += ["-i", audio]; d = int(hook_s * 1000); fc.append(f"[{ai}:a]adelay={d}|{d},apad,aformat=sample_rates=44100:channel_layouts=stereo[voice]"); vi = ai; ai += 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        fc.append(f"[{ai}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.0,afade=t=in:d=1.2,afade=t=out:st={max(total-1.8,0):.2f}:d=1.8[mus]")
        if audio: fc.append("[voice]asplit=2[v1][v2];[mus][v2]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=500[duck];[v1][duck]amix=inputs=2:duration=first:normalize=0[aout]")
        else: fc.append("[mus]anull[aout]")
        labels = ["-map", "[aout]"]
    elif audio: fc.append("[voice]anull[aout]"); labels = ["-map", "[aout]"]
    else: cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]; labels = ["-map", f"{ai}:a"]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]"] + labels + ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True); return total, len(frames), len(pages)
