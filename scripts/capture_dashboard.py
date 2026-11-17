"""Capture the dashboard screenshots used in the README from a running dashboard (real seed data, see seed_real.py).

    python scripts/capture_dashboard.py [http://localhost:3101]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3101"
OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
QUESTION = "Which address does the REST API bind to by default?"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 820}, device_scale_factor=1.5)

        def shot(path: str, name: str, full: bool = False) -> None:
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT / f"dashboard_{name}.png"), full_page=full)
            print("captured", name)

        shot("/", "overview")
        shot("/strategies", "strategies")
        shot("/graph", "graph")
        shot("/contradictions", "contradictions")
        shot("/history?subject=Python+3.14&predicate=latest+version", "history")
        page.goto(BASE + "/playground", wait_until="networkidle")
        page.fill("input[aria-label=Question]", QUESTION)
        page.get_by_role("button", name="Recall").click()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "dashboard_playground.png"), full_page=True)
        print("captured playground")
        browser.close()


if __name__ == "__main__":
    main()
