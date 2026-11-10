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
    page.wait_for_timeout(250)
    path = OUT / name
    page.screenshot(path=str(path), full_page=False)
    print("wrote", path)


def capture(page, suffix):
    page.goto(BASE + "#today", wait_until="networkidle")
    page.wait_for_selector("body[data-ready='1']")
    page.wait_for_selector(".board")
    shot(page, f"today{suffix}.png")
    page.evaluate("""() => {
      const main = document.querySelector('main');
      if (!main) return;
      main.scrollTop = 220;
      main.dispatchEvent(new Event('scroll'));
    }""")
    page.wait_for_timeout(250)
    page.screenshot(path=str(OUT / f"today-scrolled{suffix}.png"), full_page=False)
    print("wrote", OUT / f"today-scrolled{suffix}.png")

    page.click("button[data-tab='edges']")
    page.wait_for_selector(".edge-row, .empty")
    shot(page, f"edges{suffix}.png")

    page.goto(BASE + "#game/nba/401909960", wait_until="networkidle")
    page.wait_for_selector(".odd.big")
    shot(page, f"game{suffix}.png")

    page.goto(BASE + "#builder", wait_until="networkidle")
    page.fill("#sentence", "safe 4 leg parlay browns sunday +400")
    page.click("button[data-act='build']")
    page.wait_for_selector("#build-result .legline")
    page.wait_for_timeout(200)
    shot(page, f"builder{suffix}.png")

    page.click("button[data-act='use-build']")
    page.wait_for_selector(".book")
    shot(page, f"slip-browns{suffix}.png")

    page.mouse.click(30, 80)
    page.wait_for_timeout(200)
    page.goto(BASE + "#builder", wait_until="networkidle")
    page.fill("#sentence", "4 leg parlay knicks today +400")
    page.click("button[data-act='build']")
    page.wait_for_selector("#build-result .legline")
    page.click("button[data-act='use-build']")
    page.wait_for_selector(".book")
    shot(page, f"slip{suffix}.png")

    page.mouse.click(30, 80)
    page.wait_for_timeout(200)
    page.click("button[data-tab='tracker']")
    page.wait_for_selector("h1")
    shot(page, f"tracker{suffix}.png")

    page.goto(BASE + "#sgp", wait_until="networkidle")
    page.wait_for_selector(".parlay")
    shot(page, f"sgp{suffix}.png")
    page.click("button[data-mode='sgpx']")
    page.wait_for_timeout(200)
    shot(page, f"sgpx{suffix}.png")

    page.click("button[data-act='settings']")
    page.wait_for_selector(".sheet-card")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / f"settings{suffix}.png"), full_page=False)
    print("wrote", OUT / f"settings{suffix}.png")


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        for width, height, suffix in ((390, 844, ""), (430, 932, "-430")):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
                is_mobile=True,
                has_touch=True,
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            )
            page = context.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            capture(page, suffix)
            context.close()
        browser.close()
    if errors:
        print("PAGE ERRORS:")
        for err in errors:
            print(err)
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
