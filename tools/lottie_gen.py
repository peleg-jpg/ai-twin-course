#!/usr/bin/env python3
"""Palette-driven Lottie (bodymovin 5.x) generator for the AI Twin sales page.

Stdlib only. Writes six seamless-loop shape animations per palette:

    assets/lottie/<variant>/<name>.json
    assets/lottie/preview.html        (all variants x animations, inline data)

Usage:
    python3 tools/lottie_gen.py
    python3 tools/lottie_gen.py --out some/dir
    python3 tools/lottie_gen.py --palette "v6-test:#101010,#FFFFFF,#FF0066,#444444"
                                 (name:bg,ink,accent,muted - adds/overrides a variant)

Roles: accent = focal moving element, ink = main shapes, muted = secondary.
bg is never drawn (animations are transparent); it is only used by preview.html.
"""
import argparse
import json
import math
import random
from pathlib import Path

FPS = 60
SIZE = 400
C = SIZE / 2

PALETTES = {
    "v1-noir":      {"bg": "#0B0B0C", "ink": "#F4EDE3", "accent": "#FF5210", "muted": "#3A3A3F"},
    "v2-champagne": {"bg": "#F7F2E9", "ink": "#121212", "accent": "#B8975A", "muted": "#D9CFBF"},
    "v3-indigo":    {"bg": "#0E0B2B", "ink": "#FFFFFF", "accent": "#C6FF3D", "muted": "#A99BFF"},
    "v4-mirror":    {"bg": "#EEF0F3", "ink": "#1C1F24", "accent": "#2F6BFF", "muted": "#B9C0CA"},
    "v5-emerald":   {"bg": "#0F2A22", "ink": "#EFE8DA", "accent": "#C8743F", "muted": "#3F6B5C"},
}

# Easing presets as cubic-bezier (P1x, P1y, P2x, P2y) == Lottie (o.x, o.y, i.x, i.y)
LIN = (0.167, 0.167, 0.833, 0.833)
INOUT = (0.45, 0, 0.55, 1)        # easeInOutSine
INOUT3 = (0.65, 0, 0.35, 1)       # easeInOutCubic
OUT = (0.22, 1, 0.36, 1)          # easeOutQuint
OUT3 = (0.33, 1, 0.68, 1)         # easeOutCubic
IN3 = (0.32, 0, 0.67, 0)          # easeInCubic
BACK = (0.34, 1.56, 0.64, 1)      # easeOutBack (small overshoot)


# ---------------------------------------------------------------- primitives
def R(x, nd=3):
    """Round floats (recursively) and collapse integral floats to ints -> smaller JSON."""
    if isinstance(x, (list, tuple)):
        return [R(v, nd) for v in x]
    if isinstance(x, float):
        r = round(x, nd)
        return int(r) if r == int(r) else r
    return x


def rgba(hex_color):
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1]


def val(v):
    """Static property, or pass through an already-built animated one."""
    if isinstance(v, dict):
        return v
    return {"a": 0, "k": R(v)}


def _norm(keys):
    return [(k[0], k[1], (k[2] if len(k) > 2 and k[2] else LIN)) for k in keys]


def anim(keys):
    """keys: [(t, value[, ease])]. The ease shapes the segment LEAVING that key."""
    keys = _norm(keys)
    if all(k[1] == keys[0][1] for k in keys):
        return val(keys[0][1])
    out = []
    for idx, (t, v, e) in enumerate(keys):
        s = list(v) if isinstance(v, (list, tuple)) else [v]
        kf = {"t": R(t), "s": R(s)}
        if idx < len(keys) - 1:
            n = len(s)
            kf["o"] = {"x": [R(e[0])] * n, "y": [R(e[1])] * n}
            kf["i"] = {"x": [R(e[2])] * n, "y": [R(e[3])] * n}
        out.append(kf)
    return {"a": 1, "k": out}


def _lerp(a, b, f):
    if isinstance(a, (list, tuple)):
        return [x + (y - x) * f for x, y in zip(a, b)]
    return a + (b - a) * f


def _split_ease(e, u):
    """Split a cubic-bezier ease at time-fraction u (exact, de Casteljau).
    Returns (progress at u, left ease, right ease), both renormalised to the unit square."""
    p0, p1, p2, p3 = (0.0, 0.0), (e[0], e[1]), (e[2], e[3]), (1.0, 1.0)

    def bx(s):
        m = 1 - s
        return 3 * m * m * s * p1[0] + 3 * m * s * s * p2[0] + s ** 3

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if bx(mid) < u else (lo, mid)
    s = (lo + hi) / 2
    L = lambda a, b: (a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s)
    a, b, c = L(p0, p1), L(p1, p2), L(p2, p3)
    d, f = L(a, b), L(b, c)
    m = L(d, f)
    fx, fy = m
    left = LIN if abs(fy) < 1e-9 else (a[0] / fx, a[1] / fy, d[0] / fx, d[1] / fy)
    right = LIN if abs(1 - fy) < 1e-9 else (
        (f[0] - fx) / (1 - fx), (f[1] - fy) / (1 - fy),
        (c[0] - fx) / (1 - fx), (c[1] - fy) / (1 - fy))
    return fy, left, right


def phase(keys, d, L):
    """Time-shift a periodic key list (first value == last value, t in [0, L]) by d frames,
    wrapping around the loop point. The segment crossing the seam is split exactly, so
    eased motion is preserved and the loop stays seamless."""
    keys = _norm(keys)
    assert keys[0][0] == 0 and keys[-1][0] == L and keys[0][1] == keys[-1][1], "keys must be periodic"
    d %= L
    if d == 0:
        return keys
    ts = L - d
    for i in range(len(keys) - 1):
        (t0, v0, e), (t1, v1, _) = keys[i], keys[i + 1]
        if t0 < ts < t1:
            prog, le, re = _split_ease(e, (ts - t0) / (t1 - t0))
            keys = keys[:i] + [(t0, v0, le), (ts, _lerp(v0, v1, prog), re)] + keys[i + 1:]
            break
    head = [(t - ts, v, e) for t, v, e in keys if ts <= t < L]
    tail = [(t + d, v, e) for t, v, e in keys if t <= ts]
    return head + tail


# ---------------------------------------------------------------- shapes
def rect(size, pos=(0, 0), r=0):
    return {"ty": "rc", "nm": "rect", "d": 1, "s": val(size), "p": val(pos), "r": val(r)}


def ellipse(size, pos=(0, 0)):
    return {"ty": "el", "nm": "ellipse", "d": 1, "s": val(size), "p": val(pos)}


def path(v, i=None, o=None, closed=False):
    n = len(v)
    return {"ty": "sh", "nm": "path", "d": 1, "ks": {"a": 0, "k": {
        "i": R(i or [[0, 0]] * n), "o": R(o or [[0, 0]] * n), "v": R(v), "c": closed}}}


def fill(color, o=100):
    return {"ty": "fl", "nm": "fill", "c": val(color), "o": val(o), "r": 1, "bm": 0}


def stroke(color, w, o=100):
    return {"ty": "st", "nm": "stroke", "c": val(color), "o": val(o), "w": val(w),
            "lc": 2, "lj": 2, "ml": 4, "bm": 0}


def trim(e, s=0, offset=0):
    return {"ty": "tm", "nm": "trim", "s": val(s), "e": val(e), "o": val(offset), "m": 1}


def gfill_linear(color, start, end, a0, a1):
    rgb = color[:3]
    return {"ty": "gf", "nm": "gradient", "o": val(100), "r": 1, "bm": 0, "t": 1,
            "s": val(start), "e": val(end),
            "g": {"p": 2, "k": {"a": 0, "k": R([0, *rgb, 1, *rgb, 0, a0, 1, a1])}}}


def tr(p=(0, 0), a=(0, 0), s=(100, 100), r=0, o=100):
    return {"ty": "tr", "nm": "transform", "p": val(p), "a": val(a), "s": val(s),
            "r": val(r), "o": val(o), "sk": val(0), "sa": val(0)}


def group(nm, items, **t):
    return {"ty": "gr", "nm": nm, "it": list(items) + [tr(**t)], "bm": 0}


def layer(nm, shapes, op, pos=(C, C)):
    return {"ddd": 0, "ty": 4, "nm": nm, "sr": 1,
            "ks": {"o": val(100), "r": val(0), "p": val([pos[0], pos[1], 0]),
                   "a": val([0, 0, 0]), "s": val([100, 100, 100])},
            "ao": 0, "shapes": shapes, "ip": 0, "op": op, "st": 0, "bm": 0}


def comp(nm, op, layers):
    for i, ly in enumerate(layers, 1):
        ly["ind"] = i
    return {"v": "5.7.4", "fr": FPS, "ip": 0, "op": op, "w": SIZE, "h": SIZE, "nm": nm,
            "ddd": 0, "assets": [], "layers": layers, "markers": []}


# ---------------------------------------------------------------- animations
def voice_wave(p):
    """7 pill bars, organic speech-like heights, per-bar rhythm + a short 'breath' dip."""
    L, bw, pitch, hmax = 144, 22, 40, 210
    env = [0.42, 0.62, 0.84, 1.0, 0.86, 0.6, 0.44]       # centre-weighted
    segs = [8, 10, 12, 10, 12, 8, 10]                     # different rhythm per bar
    alpha = [45, 75, 100, 100, 100, 75, 45]
    rise, fall = (0.25, 0.55, 0.3, 1), (0.45, 0, 0.55, 1)
    rng = random.Random(20261017)
    groups = []
    for b in range(7):
        w = [rng.uniform(0.65, 1.35) for _ in range(segs[b])]
        times, acc = [0], 0.0
        for x in w:
            acc += x
            times.append(round(acc / sum(w) * L))
        keys = []
        for j in range(segs[b]):
            t = times[j]
            is_hi = (j % 2 == 0) == (b % 2 == 0)
            if is_hi:
                breath = 1 - 0.6 * math.exp(-((t - 96) / 14) ** 2)
                h = rng.uniform(0.55, 1.0) * env[b] * hmax * breath
            else:
                h = rng.uniform(0.1, 0.3) * env[b] * hmax
            keys.append((t, [bw, max(bw, h)], fall if is_hi else rise))
        keys.append((L, keys[0][1]))
        groups.append(group(f"bar{b + 1}", [rect(anim(keys), r=bw / 2), fill(p["accent"], alpha[b])],
                            p=((b - 3) * pitch, 0)))
    return comp("voice-wave", L, [layer("bars", groups, L)])


def rec_pulse(p):
    """Solid dot + 3 staggered rings expanding/fading (phase-wrapped, seamless)."""
    L, dot = 120, 72
    size = [(0, [dot, dot], (0.2, 0.7, 0.35, 1)), (108, [320, 320], LIN), (120, [dot, dot])]
    width = [(0, 8, (0.2, 0.6, 0.4, 1)), (108, 1.5, LIN), (120, 8)]
    alpha = [(0, 0, OUT3), (10, 80, (0.35, 0, 0.65, 1)), (108, 0, LIN), (120, 0)]
    rings = [group(f"ring{k + 1}", [ellipse(anim(phase(size, d, L))),
                                   stroke(p["accent"], anim(phase(width, d, L)), anim(phase(alpha, d, L)))])
             for k, d in enumerate((0, 40, 80))]
    pulse = []
    for c in range(3):
        pulse += [(40 * c, [100, 100], OUT3), (40 * c + 7, [111, 111], INOUT)]
    pulse.append((L, [100, 100]))
    core = group("dot", [ellipse([dot, dot]), fill(p["accent"])], s=anim(pulse))
    return comp("rec-pulse", L, [layer("pulse", [core] + rings, L)])


def scan_face(p):
    """Camera frame + corner brackets, abstract bust, scan line with trailing band."""
    L, lo, hi, rad = 180, 50, 350, 40
    # corner bracket drawn for the top-left corner, rotated into place for the others
    k, arm = 0.5523 * rad, 30
    bracket = path([[0, rad + arm], [0, rad], [rad, 0], [rad + arm, 0]],
                   i=[[0, 0], [0, 0], [-k, 0], [0, 0]], o=[[0, 0], [0, -k], [0, 0], [0, 0]])
    brackets = []
    for (cx, cy, rot, ox, oy) in [(lo, lo, 0, -1, -1), (hi, lo, 90, 1, -1),
                                  (hi, hi, 180, 1, 1), (lo, hi, 270, -1, 1)]:
        out = [cx + ox * 5, cy + oy * 5]
        keys = [(0, [cx, cy]), (45, out), (90, [cx, cy]), (135, out), (180, [cx, cy])]
        brackets.append(group("bracket", [bracket, stroke(p["ink"], 7)], p=anim(keys), r=rot))
    frame = group("frame", [rect([hi - lo, hi - lo], (C, C), rad), stroke(p["muted"], 2.5)])
    kk = 28
    shoulders = path([[108, 328], [108, 288], [160, 242], [240, 242], [292, 288], [292, 328]],
                     i=[[0, 0], [0, 0], [-kk, 0], [0, 0], [0, -kk], [0, 0]],
                     o=[[0, 0], [0, -kk], [0, 0], [kk, 0], [0, 0], [0, 0]], closed=True)
    bust = group("bust", [ellipse([92, 110], (C, 172)), shoulders, fill(p["muted"])])
    band = group("band", [rect([244, 64], (0, -32)),
                          gfill_linear(p["accent"], (0, -64), (0, 0), 0, 0.38)],
                 s=anim([(0, [100, 2], (0.3, 0, 0.3, 1)), (50, [100, 100], LIN),
                         (150, [100, 100], LIN), (180, [100, 2])]))
    line = group("line", [path([[-122, 0], [122, 0]]), stroke(p["accent"], 4),
                          stroke(p["accent"], 14, 20)])
    scan = group("scan", [line, band],
                 p=anim([(0, [C, 76], (0.42, 0, 0.58, 1)), (150, [C, 324], LIN), (180, [C, 76])]),
                 o=anim([(0, 0, OUT3), (18, 100, LIN), (134, 100, INOUT), (152, 0, LIN), (180, 0)]))
    return comp("scan-face", L, [layer("scan", [scan] + brackets + [bust, frame], L, pos=(0, 0))])


def edit_timeline(p):
    """3 tracks; clips snap in, one clip is cut (gap opens, then closes), playhead sweeps."""
    L, x0, x1 = 240, 64, 336
    rows = {1: (166, 40, 9), 2: (216, 40, 9), 3: (262, 26, 7)}       # cy, height, radius
    # --- playhead
    knob = group("knob", [ellipse([16, 16], (0, 110)), fill(p["accent"])], a=(0, 110), p=(0, 110),
                 s=anim([(0, [100, 100], LIN), (98, [100, 100], OUT3), (106, [140, 140], INOUT),
                         (126, [100, 100], LIN), (L, [100, 100])]))
    head = group("playhead", [knob, group("line", [path([[0, 112], [0, 286]]), stroke(p["accent"], 4)])],
                 p=anim([(0, [x0, 0], LIN), (28, [x0, 0], INOUT3), (100, [206, 0], LIN),
                         (132, [206, 0], INOUT3), (204, [x1, 0], LIN), (222, [x1, 0], LIN), (L, [x0, 0])]),
                 o=anim([(0, 0, LIN), (14, 0, OUT3), (28, 100, LIN), (204, 100, INOUT), (220, 0, LIN), (L, 0)]))

    def span(a, b, row):
        cy, h, _ = rows[row]
        return [(a + b) / 2, cy], [b - a, h]

    def clip_rect(row, keys):
        """keys: [(t, (a, b)[, ease])] horizontal extent over time."""
        keys = _norm(keys)
        if len(keys) == 1:
            pos, sz = span(*keys[0][1], row)
            return rect(sz, pos, rows[row][2])
        return rect(anim([(t, span(*ab, row)[1], e) for t, ab, e in keys]),
                    anim([(t, span(*ab, row)[0], e) for t, ab, e in keys]), rows[row][2])

    def clip(nm, order, rects, color, alpha=100):
        tin, tout = 6 + 6 * order, 204 + 3 * order
        dx = 36
        return group(nm, rects + [fill(color, alpha)],
                     p=anim([(0, [dx, 0], LIN), (tin, [dx, 0], BACK), (tin + 26, [0, 0], LIN),
                             (tout, [0, 0], IN3), (tout + 18, [-14, 0], LIN), (L, [dx, 0])]),
                     o=anim([(0, 0, LIN), (tin, 0, OUT3), (tin + 16, 100, LIN),
                             (tout, 100, INOUT), (tout + 18, 0, LIN), (L, 0)]))

    reset = 222 + 3
    # the cut clip: two overlapping halves read as one clip until the cut at t=100
    cut_left = clip_rect(1, [(0, (130, 212), LIN), (100, (130, 212), OUT3), (110, (130, 203), LIN),
                             (reset, (130, 203), LIN), (L, (130, 212))])
    cut_right = clip_rect(1, [(0, (200, 282), LIN), (100, (200, 282), OUT), (116, (235, 308), LIN),
                              (128, (235, 308), BACK), (150, (209, 282), LIN),
                              (reset, (209, 282), LIN), (L, (200, 282))])
    clips = [
        clip("t1-a", 0, [clip_rect(1, [(0, (x0, 124))])], p["ink"]),
        clip("t1-cut", 1, [cut_left, cut_right], p["ink"]),
        clip("t2-a", 2, [clip_rect(2, [(0, (x0, 186))])], p["muted"]),
        clip("t2-b", 3, [clip_rect(2, [(0, (192, x1))])], p["muted"]),
        clip("t3-a", 4, [clip_rect(3, [(0, (x0, 228))])], p["muted"], 70),
        clip("t3-b", 5, [clip_rect(3, [(0, (234, 320))])], p["muted"], 70),
    ]
    lanes = group("lanes", [rect([x1 - x0 + 8, h + 8], (C, cy), r + 4) for cy, h, r in rows.values()]
                  + [fill(p["muted"], 22)])
    ticks = [path([[x0 + i * 27.2, 120 if i % 2 == 0 else 125], [x0 + i * 27.2, 130]]) for i in range(11)]
    ruler = group("ruler", ticks + [stroke(p["muted"], 2.5)])
    return comp("edit-timeline", L, [layer("timeline", [head] + clips + [lanes, ruler], L, pos=(0, 0))])


def check_draw(p):
    """Track ring, accent circle draws (trim), check draws, pop, hold, fade, loop."""
    L, D = 150, 210
    circle = group("circle", [ellipse([D, D]), trim(anim([(0, 0, LIN), (4, 0, (0.6, 0, 0.3, 1)), (46, 100, LIN),
                                                         (138, 100, LIN), (L, 0)])),
                              stroke(p["accent"], 12)])
    check = group("check", [path([[-50, 2], [-15, 36], [52, -34]]),
                            trim(anim([(0, 0, LIN), (38, 0, (0.55, 0, 0.25, 1)), (68, 100, LIN),
                                       (138, 100, LIN), (L, 0)])),
                            stroke(p["ink"], 17)])
    disc = group("disc", [ellipse([D, D]),
                          fill(p["accent"], anim([(0, 0, LIN), (40, 0, OUT3), (72, 14, LIN), (138, 14, LIN), (L, 0)]))],
                 s=anim([(0, [70, 70], LIN), (40, [70, 70], OUT), (80, [100, 100], LIN), (138, [100, 100], LIN),
                         (L, [70, 70])]))
    track = group("track", [ellipse([D, D]), stroke(p["muted"], 12)])
    root = group("badge", [check, circle, disc, track],
                 s=anim([(0, [100, 100], LIN), (66, [100, 100], OUT3), (76, [107, 107], INOUT),
                         (96, [100, 100], LIN), (112, [100, 100], INOUT), (136, [94, 94], LIN), (L, [100, 100])]),
                 o=anim([(0, 0, OUT3), (8, 100, LIN), (112, 100, INOUT), (136, 0, LIN), (L, 0)]))
    return comp("check-draw", L, [layer("check", [root], L)])


def typing_dots(p):
    """Chat bubble (RTL: tail bottom-right) with 3 dots bouncing in sequence."""
    L, cy = 84, -18
    style = lambda w: [stroke(p["ink"], w), fill(p["muted"], 30)]
    dots = []
    for k in range(3):
        s, x = 6 + 11 * k, (k - 1) * 52
        dots.append(group(f"dot{k + 1}", [ellipse([26, 26]), fill(p["accent"])],
                          p=anim([(0, [x, cy], LIN), (s, [x, cy], (0.33, 0.8, 0.45, 1)),
                                  (s + 13, [x, cy - 24], (0.5, 0, 0.5, 1)), (s + 30, [x, cy], LIN), (L, [x, cy])]),
                          o=anim([(0, 55, LIN), (s, 55, OUT3), (s + 13, 100, INOUT), (s + 30, 55, LIN), (L, 55)])))
    bubble = group("bubble", dots + [
        group("tail2", [ellipse([12, 12], (131, 75))] + style(3.5)),
        group("tail1", [ellipse([24, 24], (115, 52))] + style(4)),
        group("body", [rect([256, 124], (0, cy), 62)] + style(5)),
    ], s=anim([(0, [100, 100]), (42, [101.5, 101.5]), (L, [100, 100])]), a=(0, cy), p=(0, cy))
    return comp("typing-dots", L, [layer("typing", [bubble], L)])


ANIMATIONS = {
    "voice-wave": voice_wave,
    "rec-pulse": rec_pulse,
    "scan-face": scan_face,
    "edit-timeline": edit_timeline,
    "check-draw": check_draw,
    "typing-dots": typing_dots,
}


def build(palette_hex):
    p = {role: rgba(hx) for role, hx in palette_hex.items()}
    return {name: fn(p) for name, fn in ANIMATIONS.items()}


# ---------------------------------------------------------------- preview
PREVIEW = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lottie preview</title>
<style>
  :root{--cell:180px}
  body{margin:0;padding:16px;background:#151515;color:#ccc;font:12px/1.3 system-ui,sans-serif}
  .grid{display:grid;grid-template-columns:110px repeat(6,var(--cell));gap:8px;align-items:center}
  .h{text-align:center;font-weight:600;color:#eee}
  .v{font-weight:600;color:#eee}
  .cell{width:var(--cell);height:var(--cell);border-radius:10px}
  .cell>div{width:100%;height:100%}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js"
  integrity="sha384-J8C0MvgX4WP58J4N2W99vCKd2J6z99ynOJ5bEfE6jeP7kVTW1drYtv/jzrxM5jbm" crossorigin="anonymous"></script>
</head><body>
<div class="grid" id="grid"></div>
<script>
const PALETTES = __PALETTES__;
const DATA = __DATA__;
const NAMES = __NAMES__;
const grid = document.getElementById('grid');
window.__anims = [];
grid.insertAdjacentHTML('beforeend', '<div></div>' + NAMES.map(n => `<div class="h">${n}</div>`).join(''));
for (const v of Object.keys(DATA)) {
  grid.insertAdjacentHTML('beforeend', `<div class="v">${v}</div>`);
  for (const n of NAMES) {
    const cell = document.createElement('div');
    cell.className = 'cell';
    cell.style.background = PALETTES[v].bg;
    const box = document.createElement('div');
    box.dataset.variant = v; box.dataset.name = n;
    cell.appendChild(box); grid.appendChild(cell);
    const a = lottie.loadAnimation({container: box, renderer: 'svg', loop: true, autoplay: true,
                                    animationData: DATA[v][n]});
    a.__id = v + '/' + n;
    window.__anims.push(a);
  }
}
// seek every animation to the same fraction of its own loop (used for screenshots)
window.seekAll = f => window.__anims.forEach(a => a.goToAndStop(f * a.totalFrames, true));
</script></body></html>
"""


def write_preview(out_dir, data, palettes):
    html = (PREVIEW.replace("__PALETTES__", json.dumps(palettes))
            .replace("__DATA__", json.dumps(data, separators=(",", ":")))
            .replace("__NAMES__", json.dumps(list(ANIMATIONS))))
    (out_dir / "preview.html").write_text(html, encoding="utf-8")


def main():
    default_out = Path(__file__).resolve().parent.parent / "assets" / "lottie"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=default_out)
    ap.add_argument("--palette", action="append", default=[],
                    help='extra variant "name:#bg,#ink,#accent,#muted"')
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    palettes = dict(PALETTES)
    for spec in args.palette:
        name, colors = spec.split(":", 1)
        palettes[name] = dict(zip(("bg", "ink", "accent", "muted"), colors.split(",")))

    all_data = {}
    for variant, pal in palettes.items():
        vdir = args.out / variant
        vdir.mkdir(parents=True, exist_ok=True)
        all_data[variant] = build(pal)
        for name, data in all_data[variant].items():
            f = vdir / f"{name}.json"
            f.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            kb = f.stat().st_size / 1024
            print(f"{variant}/{name}.json  {kb:5.1f} KB{'  <-- OVER 25KB' if kb >= 25 else ''}")
    if not args.no_preview:
        write_preview(args.out, all_data, palettes)
        print(f"preview: {args.out / 'preview.html'}")


if __name__ == "__main__":
    main()
