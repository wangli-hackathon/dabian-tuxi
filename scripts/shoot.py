"""给演示模式拍几张图。需要本机 Chrome 和已启动的 Gradio。"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from game.samples import DEMO_ANSWERS

URL = os.environ.get("DABIAN_URL", "http://127.0.0.1:17421")
OUT = Path(os.environ.get("DABIAN_SHOTS", "/tmp/dabian-shots"))
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name: str, locator=None) -> None:
    path = OUT / name
    if locator is None:
        page.screenshot(path=str(path), full_page=True)
    else:
        locator.screenshot(path=str(path))
    print(path, path.stat().st_size)


def answer(page, text: str) -> None:
    label = page.locator("[data-testid=round-label]").inner_text().strip()
    box = page.get_by_label("你的回答")
    box.click()
    box.fill(text)
    page.get_by_role("button", name="作答", exact=True).click()
    page.wait_for_function(
        """(prev) => {
            const label = document.querySelector('[data-testid="round-label"]');
            const outcome = document.querySelector('[data-testid="outcome"]');
            return Boolean(outcome) || (label && label.textContent.trim() !== prev);
        }""",
        arg=label,
        timeout=20000,
    )


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome-stable",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--font-render-hinting=none"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.get_by_role("button", name="坐上答辩席").wait_for(timeout=20000)
        page.wait_for_timeout(600)
        page.get_by_label("答辩人怎么称呼").fill("小陈")
        shot(page, "dabian-setup.png", page.locator(".hero"))
        page.screenshot(path=str(OUT / "dabian-setup-page.png"), full_page=True)

        page.get_by_role("button", name="坐上答辩席").click()
        page.get_by_text("第 1 轮").first.wait_for(timeout=20000)
        page.wait_for_timeout(400)
        shot(page, "dabian-round1.png", page.locator("[data-testid=arena]"))

        answer(page, DEMO_ANSWERS[0])
        answer(page, DEMO_ANSWERS[1])
        answer(page, DEMO_ANSWERS[2])
        page.wait_for_timeout(500)
        shot(page, "dabian-battle.png", page.locator("[data-testid=arena]"))

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        # 新开页会丢状态，手机截图改在当前页缩放。
        mobile.close()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        shot(page, "dabian-mobile.png", page.locator("[data-testid=arena]"))
        page.set_viewport_size({"width": 1280, "height": 900})

        answer(page, DEMO_ANSWERS[3])
        answer(page, DEMO_ANSWERS[4])
        answer(page, DEMO_ANSWERS[5])
        page.get_by_text("答辩通过").first.wait_for(timeout=10000)
        page.wait_for_timeout(500)
        shot(page, "dabian-report.png", page.locator("[data-testid=arena]"))

        page.get_by_role("button", name="返回准备").click()
        page.get_by_role("button", name="坐上答辩席").wait_for(timeout=15000)
        page.get_by_role("button", name="坐上答辩席").click()
        page.get_by_text("第 1 轮").first.wait_for(timeout=15000)
        for _ in range(4):
            answer(page, "不知道")
        page.get_by_text("延毕警告").first.wait_for(timeout=10000)
        page.wait_for_timeout(500)
        shot(page, "dabian-fail.png", page.locator("[data-testid=arena]"))
        browser.close()


if __name__ == "__main__":
    main()
