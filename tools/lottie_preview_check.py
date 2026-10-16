#!/usr/bin/env python3
"""Render assets/lottie/preview.html in headless Chromium (Python Playwright) and validate.

- waits for all animations to load, checks they advance on their own (not frozen)
- checks every SVG actually drew shapes
- collects console errors / page errors
- seeks every animation to 3 fractions of its loop -> preview-t1.png .. preview-t3.png
Exit code 1 on any problem.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "assets" / "lottie"
FRACTIONS = (0.2, 0.5, 0.8)


def main():
    problems, logs = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1290, "height": 1060})
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
        page.goto((OUT / "preview.html").as_uri())
        page.wait_for_function("window.__anims && __anims.length === 30 && __anims.every(a => a.isLoaded)",
                               timeout=15000)
        f0 = page.evaluate("__anims.map(a => a.currentFrame)")
        page.wait_for_timeout(600)
        f1 = page.evaluate("__anims.map(a => a.currentFrame)")
        ids = page.evaluate("__anims.map(a => a.__id)")
        for i, (a, b) in enumerate(zip(f0, f1)):
            if a == b:
                problems.append(f"frozen: {ids[i]}")
        drawn = page.evaluate("""__anims.map(a => {
            const ps = [...a.wrapper.querySelectorAll('path')].filter(p => (p.getAttribute('d') || '').length > 2);
            return ps.length; })""")
        for i, n in enumerate(drawn):
            if n == 0:
                problems.append(f"nothing drawn: {ids[i]}")
        for i, frac in enumerate(FRACTIONS, 1):
            page.evaluate(f"seekAll({frac})")
            page.wait_for_timeout(100)
            page.screenshot(path=str(OUT / f"preview-t{i}.png"), full_page=True)
        browser.close()

    errors = [l for l in logs if l.startswith(("[error]", "[pageerror]", "[warning]"))]
    print(f"animations advancing: {sum(a != b for a, b in zip(f0, f1))}/30")
    print(f"svg path counts: min {min(drawn)} max {max(drawn)}")
    print("console:", *(logs or ["(empty)"]), sep="\n  ")
    for p in problems + errors:
        print("PROBLEM:", p)
    sys.exit(1 if problems or errors else 0)


if __name__ == "__main__":
    main()
