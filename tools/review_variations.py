"""Independent review of the variation pages: copy coverage, banned characters, console errors, overflow, timers.
Usage: python3 tools/review_variations.py [variant ...]   (server must be running on 127.0.0.1:8797)
"""
import re, sys, json, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8797/variations/"
VARIANTS = sys.argv[1:] or ["v1-noir", "v2-champagne", "v3-indigo", "v4-mirror", "v5-emerald"]
META_KEYS = {"MEDIA", "NOTE", "DEADLINE", "TIMER LABELS", "H1 EMPHASIS", "PHOTOS", "CARDS", "FIELDS", "TIMER"}


def norm(s):
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def copy_segments(md_text):
    main, _, thanks = md_text.partition("# עמוד תודה")
    def segs(block):
        out = []
        for raw in block.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("---") or line.startswith("כללים") or line.startswith("- הקופי") or line.startswith("- [[") or line.startswith("- שורה") or line.startswith("- ״"):
                continue
            m = re.match(r"^([A-Z][A-Z0-9 \-]*?)(?:\s*\([^)]*\))?:\s*(.*)$", line)
            if m:
                key, val = m.group(1).strip(), m.group(2).strip()
                if key.split(" (")[0] in META_KEYS or not val:
                    continue
                if key == "SIGN-OFF":
                    out += [p.strip() for p in val.split("/") if p.strip()]
                    continue
                if key == "BADGE":
                    continue
                if "(קישורים" in val:
                    continue
                out.append(val)
                continue
            if line.startswith("- "):
                parts = [p.strip() for p in line[2:].split("|")]
                out += [p for p in parts if p and not p.startswith("lottie:")]
                continue
            out.append(line)
        return out
    return segs(main), segs(thanks)


def check_text(segments, text):
    t = norm(text)
    missing = []
    for s in segments:
        s2 = norm(re.sub(r"\(.*?קו חוצה.*?\)|\(שורה קטנה.*?\)", "", s))
        s2 = s2.split(" (")[0] if s2.endswith(")") and "[[" not in s2 else s2
        if s2 and s2 not in t:
            missing.append(s2)
    return missing


def main():
    md = (ROOT / "copy/page-copy.md").read_text(encoding="utf-8")
    page_segs, thanks_segs = copy_segments(md)
    report = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for v in VARIANTS:
            r = report[v] = {}
            html_path = ROOT / "variations" / v / "index.html"
            if not html_path.exists():
                r["error"] = "index.html missing"; continue
            raw = html_path.read_text(encoding="utf-8")
            r["long_dashes"] = len(re.findall(r"[—–]", raw))
            r["backdrop_filter"] = raw.count("backdrop-filter")
            for name, url, segs in [("page", BASE + v + "/index.html", page_segs), ("thanks", BASE + v + "/thank-you.html", thanks_segs)]:
                for w, h in [(360, 780), (390, 844), (1440, 900)]:
                    ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                    pg = ctx.new_page()
                    errs = []
                    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.goto(url, wait_until="networkidle")
                    total = pg.evaluate("document.documentElement.scrollHeight")
                    y = 0
                    while y < total:
                        y += 500; pg.evaluate(f"window.scrollTo(0,{y})"); pg.wait_for_timeout(60)
                        total = pg.evaluate("document.documentElement.scrollHeight")
                    pg.wait_for_timeout(800)
                    key = f"{name}@{w}"
                    r[key] = {
                        "overflow_px": pg.evaluate("document.documentElement.scrollWidth - innerWidth"),
                        "console_errors": [e for e in errs if "facebook" not in e][:5],
                    }
                    if w == 390:
                        text = pg.evaluate("document.body.innerText + ' ' + document.body.textContent")
                        r[key]["missing_copy"] = check_text(segs, text)
                        if name == "page":
                            r[key]["timers"] = pg.evaluate("[...document.querySelectorAll('[data-countdown]')].map(e=>e.innerText.replace(/\\s+/g,''))")
                            r[key]["sections"] = pg.evaluate("Array.from({length:19},(_,i)=>'s'+i).filter(id=>!document.getElementById(id))")
                            r[key]["invisible_opacity0"] = pg.evaluate("""[...document.querySelectorAll('main *, section *')].filter(e=>{const s=getComputedStyle(e);return s.opacity==='0' && e.innerText && e.innerText.trim().length>8 && !e.closest('[hidden],[aria-hidden=true]')}).slice(0,5).map(e=>e.innerText.trim().slice(0,40))""")
                    ctx.close()
        b.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
