#!/usr/bin/env python3
"""Optional real-browser acceptance and screenshot/video capture for local demo.

Requires separately installed Playwright and Chromium. Run locally, never on
production or with a real school. No repository integration dependencies added.
"""
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]


def wait_for_demo(proc):
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError("Synthetic demo server terminated before readiness")
        try:
            with urllib.request.urlopen(BASE + "/local-demo/", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError("Synthetic demo server did not become ready on loopback")


def main():
    try:
        from playwright.sync_api import sync_playwright, expect
    except ImportError:
        raise SystemExit(
            "Playwright not installed. Install it separately and install Chromium; "
            "do not change Jireh runtime requirements."
        )

    output = ROOT / "artifacts" / "synthetic-demo"
    output.mkdir(parents=True, exist_ok=True)
    runner = [sys.executable, str(ROOT / "scripts" / "run_local_browser_demo.py")]
    proc = subprocess.Popen(runner, cwd=ROOT)
    try:
        wait_for_demo(proc)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                record_video_dir=str(output),
            )
            page = context.new_page()
            page.goto(BASE + "/local-demo/", wait_until="networkidle")
            expect(page.get_by_text("LOCAL SYNTHETIC DEMO")).to_be_visible()
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Choose a persona")
            page.get_by_role("button", name="Family applicant").click()
            expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            expect(page.locator("#school-name")).to_have_text("Synthetic Christian Academy")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("View household")
            page.get_by_role("button", name="Create / resume annual draft").click()
            expect(page.locator("#draft-status")).to_have_text("DRAFT")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Create annual draft")
            for selected_count in range(2):
                page.locator("#children button").filter(has_text="Select child").first.click()
                # Wait for each async POST and UI refresh before the next click.
                expect(
                    page.locator("#children button").filter(has_text="Selected")
                ).to_have_count(selected_count + 1)
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Select children")
            # Wait for the new session, not stale text from the previous persona.
            page.get_by_role("button", name="Family applicant").click()
            expect(page.locator("#family")).to_be_visible()
            expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            expect(page.locator("#draft-status")).to_have_text("DRAFT")
            expect(page.locator("#children button").filter(has_text="Selected")).to_have_count(2)
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Select children")
            page.get_by_role("button", name="Verify School B access is denied").click()
            expect(page.locator("#events")).to_contain_text("PASS: School B family draft denied (404)")
            page.get_by_role("button", name="Verify CSRF protection").click()
            expect(page.locator("#events")).to_contain_text("PASS: Missing CSRF header rejected (403)")
            page.screenshot(path=str(output / "family-journey.png"), full_page=True)

            page.get_by_role("button", name="School A director").click()
            expect(page.locator("#application-count")).to_have_text("1")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Director review")
            page.get_by_role("button", name="Verify other school is denied").click()
            expect(page.locator("#events")).to_contain_text(
                "PASS: Another school's director inventory denied (404)"
            )
            page.screenshot(path=str(output / "director-journey.png"), full_page=True)

            page.get_by_role("button", name="School B director").click()
            expect(page.locator("#application-count")).to_have_text("0")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Director review")
            page.get_by_role("button", name="Verify other school is denied").click()
            expect(page.locator("#events")).to_contain_text(
                "PASS: Another school's director inventory denied (404)"
            )
            page.screenshot(path=str(output / "other-school-journey.png"), full_page=True)
            context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    print("Browser demo passed. Synthetic-only screenshots and video:", output)


if __name__ == "__main__":
    main()
