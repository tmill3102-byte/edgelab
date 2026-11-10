#!/usr/bin/env python3
"""iPhone-size screenshots of the local EdgeLab site."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/opt/cursor/artifacts/preview")
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("EDGELAB_URL", "http://127.0.0.1:8765/")


def shot(page, name):
    page.evaluate("() => { window.scrollTo(0, 0); document.querySelector('main')?.scrollTo(0, 0); }")
    page.wait_for_timeout(200)
    path = OUT / name
    page.screenshot(path=str(path), full_page=False)
    print("wrote", path)


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        )
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("body[data-ready='1']")
        shot(page, "today.png")

        page.click("button[data-tab='edges']")
        page.wait_for_selector("h1")
        shot(page, "edges.png")

        page.goto(BASE + "#game/nba/401909960", wait_until="networkidle")
        page.wait_for_selector(".pick")
        shot(page, "game.png")

        page.goto(BASE + "#builder", wait_until="networkidle")
        page.fill("#sentence", "safe 4 leg parlay browns sunday +400")
        page.click("button[data-act='build']")
        page.wait_for_selector("#build-result .leg")
        page.wait_for_timeout(200)
        shot(page, "builder.png")

        page.click("button[data-act='use-build']")
        page.wait_for_selector(".book")
        shot(page, "slip-browns.png")

        page.goto(BASE + "#builder", wait_until="networkidle")
        page.fill("#sentence", "4 leg parlay knicks today +400")
        page.click("button[data-act='build']")
        page.wait_for_selector("#build-result .leg")
        page.click("button[data-act='use-build']")
        page.wait_for_selector(".book")
        shot(page, "slip.png")

        page.click("button[data-tab='tracker']")
        page.wait_for_selector("h1")
        shot(page, "tracker.png")

        page.goto(BASE + "#sgp", wait_until="networkidle")
        page.wait_for_selector("h1")
        page.wait_for_selector(".sgp-leg")
        shot(page, "sgp.png")
        page.click("button[data-mode='sgpx']")
        page.wait_for_timeout(200)
        shot(page, "sgpx.png")
        browser.close()
    if errors:
        print("PAGE ERRORS:")
        for err in errors:
            print(err)
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
