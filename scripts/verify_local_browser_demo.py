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


def verify_customer_workspace(sync_playwright, expect, output, runner):
    """Use a fresh disposable database, independent of the guided demo."""
    proc = subprocess.Popen(runner, cwd=ROOT)
    try:
        wait_for_demo(proc)
        # The older loopback-only fixture page already exposes its generated
        # throwaway password. Read it here solely for generic sign-in testing.
        # The customer workspace never includes fixture credentials.
        import json
        import re
        with urllib.request.urlopen(BASE + "/local-demo/", timeout=5) as response:
            fixture = response.read().decode("utf-8")
        match = re.search(r'const PASSWORD = "([^"]+)";', fixture)
        if match is None:
            raise RuntimeError("Disposable fixture credential unavailable")
        password = json.loads('"' + match.group(1) + '"')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            def sign_in(username):
                page.goto(BASE + "/workspace/")
                expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
                page.get_by_label("Username").fill(username)
                page.get_by_label("Password").fill(password)
                page.get_by_role("button", name="Sign in", exact=True).click()
                expect(page.get_by_role("heading", name="Your workspace")).to_be_visible()

            def sign_out():
                page.get_by_role("button", name="Sign out").click()
                expect(page.get_by_role("heading", name="Sign in")).to_be_visible()

            sign_in("local-demo-family")
            expect(page.get_by_role("heading", name="Family applications")).to_be_visible()
            expect(page.get_by_role("heading", name="School director")).to_have_count(0)
            page.get_by_role("link", name=re.compile("Sample Family")).click()
            family_url = page.url
            expect(page.locator("#draft-state")).to_have_text("No draft exists for this year.")

            def phantom_create(route):
                if route.request.method == "POST":
                    route.fulfill(status=200, content_type="application/json",
                                  body='{"id":"fictional-phantom","status":"DRAFT"}')
                else:
                    route.continue_()

            page.route("**/workspace/family/**/draft/", phantom_create)
            with page.expect_navigation():
                page.get_by_role("button", name="Create annual draft").click()
            expect(page.locator("#draft-state")).to_have_text("No draft exists for this year.")
            page.unroute("**/workspace/family/**/draft/", phantom_create)
            page.get_by_role("button", name="Create annual draft").click()
            expect(page.locator("#draft-state")).to_have_text("DRAFT — saved")
            page.get_by_role("button", name="Include Jordan").click()
            expect(page.locator("#selected-count")).to_have_text("1 selected")
            page.get_by_role("button", name="Include Taylor").click()
            expect(page.locator("#selected-count")).to_have_text("2 selected")
            page.reload()
            expect(page.locator("#selected-count")).to_have_text("2 selected")
            page.screenshot(path=str(output / "customer-workspace-family.png"), full_page=True)
            with page.expect_response(lambda res: res.url.endswith("/questionnaire/") and res.request.method == "GET") as loaded:
                page.get_by_role("link", name="Open financial questionnaire").click()
            assert loaded.value.headers.get("referrer-policy") == "same-origin"
            questionnaire_url = page.url
            expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 0")
            page.locator("#id_income-0-category").select_option("EMPLOYMENT")
            page.locator("#id_income-0-value").fill("1234.56")
            page.locator("#id_income-0-period_start").fill("2026-01-01")
            page.locator("#id_income-0-period_end").fill("2026-12-31")
            page.get_by_role("button", name="Add income row").click()
            page.locator("#id_income-1-category").select_option("SUPPORT")
            page.locator("#id_income-1-value").fill("100")
            page.locator("#id_income-1-period_start").fill("2026-01-01")
            page.locator("#id_income-1-period_end").fill("2026-12-31")
            page.locator("#id_assets-0-category").select_option("CASH")
            page.locator("#id_assets-0-value").fill("500")
            page.locator("#id_assets-0-as_of_date").fill("2026-06-30")
            page.locator("#id_liabilities-0-category").select_option("MORTGAGE")
            page.locator("#id_liabilities-0-value").fill("900")
            page.locator("#id_liabilities-0-as_of_date").fill("2026-06-30")
            page.locator("#id_expenses-0-category").select_option("HOUSING")
            page.locator("#id_expenses-0-value").fill("200")
            page.locator("#id_expenses-0-period_start").fill("2026-01-01")
            page.locator("#id_expenses-0-period_end").fill("2026-01-31")
            page.get_by_label("Include the example checklist?").select_option("no")
            with page.expect_response(lambda res: res.url == questionnaire_url and res.request.method == "POST") as written:
                page.get_by_role("button", name="Save fictional answers").click()
            assert written.value.status == 302, f"Questionnaire save HTTP {written.value.status}"
            expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 1")
            page.reload()
            expect(page.locator("#id_income-0-value")).to_have_value("1234.56")
            expect(page.locator("#id_income-1-category")).to_have_value("SUPPORT")
            expect(page.locator("#id_assets-0-category")).to_have_value("CASH")
            expect(page.locator("#id_liabilities-0-category")).to_have_value("MORTGAGE")
            expect(page.locator("#id_expenses-0-category")).to_have_value("HOUSING")
            expect(page.get_by_label("Include the example checklist?")).to_have_value("no")
            page.locator("#id_income-0-value").fill("765.43")
            page.locator("#id_income-1-DELETE").check()
            page.get_by_role("button", name="Save fictional answers").click()
            expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 2")
            expect(page.locator("#id_income-0-value")).to_have_value("765.43")
            expect(page.locator("#id_income-1-category")).to_have_value("")
            page.screenshot(path=str(output / "customer-workspace-questionnaire.png"), full_page=True)
            page.get_by_role("link", name="Return to annual application").click()
            page.get_by_role("link", name="Manage supporting documents").click()
            documents_url = page.url
            expect(page.locator("#document-count")).to_have_text("0 listed")

            def select_and_save_sample(label, expected_count):
                with page.expect_download() as downloaded:
                    page.get_by_role("link", name=label).click()
                path = downloaded.value.path()
                original_bytes = path.read_bytes()
                page.locator("#document-file").set_input_files(str(path))
                with page.expect_response(lambda res: res.url.endswith("/documents/upload/") and res.request.method == "POST") as uploaded:
                    page.get_by_role("button", name="Save fictional document").click()
                assert uploaded.value.status == 200, f"Document upload HTTP {uploaded.value.status}"
                expect(page.locator("#document-count")).to_have_text(f"{expected_count} listed")
                return original_bytes

            original = select_and_save_sample("Original fictional PDF", 1)
            original_row = page.locator('[data-document-version="1"]')
            original_read_url = BASE + original_row.get_by_role("link", name="Download saved PDF").get_attribute("href")
            assert page.request.get(original_read_url).body() == original
            corrected = select_and_save_sample("Corrected fictional PDF", 2)
            assert corrected != original
            corrected_row = page.locator('[data-document-version="2"]')
            corrected_read_url = BASE + corrected_row.get_by_role("link", name="Download saved PDF").get_attribute("href")
            with page.expect_download() as saved_download:
                corrected_row.get_by_role("link", name="Download saved PDF").click()
            assert saved_download.value.path().read_bytes() == corrected
            page.get_by_role("button", name="Remove version 1").click()
            expect(page.locator("#document-count")).to_have_text("1 listed")
            assert page.request.get(original_read_url).status == 404
            page.reload()
            expect(page.locator('[data-document-version="2"]')).to_be_visible()
            page.screenshot(path=str(output / "customer-workspace-documents.png"), full_page=True)
            page.get_by_role("link", name="Return to annual application").click()
            page.get_by_role("link", name="Review fictional application").click()
            expect(page.locator("#review-status")).to_have_text("Review required")
            expect(page.locator("#submission-state")).to_have_text("Application state: DRAFT")
            expect(page.locator("#submission-fee")).to_have_text("Annual household fee at submission: $55.00 USD")
            expect(page.locator('[data-submission-blocker="submission_review_confirmation_required"]')).to_be_visible()
            expect(page.locator("#submission-readiness-status")).to_have_text("Final submission unavailable")
            page.get_by_role("checkbox", name="I reviewed this saved fictional application.").check()
            page.get_by_role("button", name="Confirm fictional review").click()
            expect(page.locator("#review-status")).to_have_text("Current fictional review confirmed")
            expect(page.locator('[data-submission-blocker="submission_review_confirmation_required"]')).to_have_count(0)
            expect(page.locator('[data-submission-blocker="submission_disclosure_not_approved"]')).to_be_visible()
            expect(page.locator('[data-submission-blocker="submission_payment_unreconciled"]')).to_be_visible()
            expect(page.locator("#submission-readiness-status")).to_have_text("Final submission unavailable")
            page.screenshot(path=str(output / "customer-workspace-review.png"), full_page=True)
            review_url = page.url
            page.goto(questionnaire_url)
            page.get_by_label("Include the example checklist?").select_option("yes")
            page.get_by_role("button", name="Save fictional answers").click()
            expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 3")
            page.goto(review_url)
            expect(page.locator("#review-status")).to_have_text("Review required")
            expect(page.locator("#submission-revision")).to_have_text("Reviewed financial revision: 3")
            expect(page.locator('[data-submission-blocker="submission_review_confirmation_required"]')).to_be_visible()
            expect(page.locator('[data-submission-blocker="submission_payment_unreconciled"]')).to_be_visible()
            expect(page.get_by_text("Include the example checklist? · Yes · v1", exact=True)).to_be_visible()
            page.get_by_role("checkbox", name="I reviewed this saved fictional application.").check()
            page.get_by_role("button", name="Confirm fictional review").click()
            expect(page.locator("#review-status")).to_have_text("Current fictional review confirmed")
            sign_out()
            assert page.request.get(review_url).status == 403
            assert page.request.get(documents_url).status == 403
            assert page.request.get(corrected_read_url).status == 403
            assert page.request.get(family_url).status == 403
            assert page.request.get(questionnaire_url).status == 403

            sign_in("local-demo-director-a")
            expect(page.get_by_role("heading", name="Family applications")).to_have_count(0)
            page.get_by_role("link", name=re.compile("Synthetic Christian Academy")).click()
            director_a_url = page.url
            expect(page.locator("#draft-total")).to_have_text("1")
            expect(page.locator("#household-total")).to_have_text("1")
            expect(page.locator("#child-total")).to_have_text("2")
            page.screenshot(path=str(output / "customer-workspace-director.png"), full_page=True)
            page.get_by_role("link", name="Open case").click()
            case_url = page.url
            expect(page.locator("#case-child-count")).to_have_text("2")
            assert page.request.get(family_url).status == 404
            assert page.request.get(questionnaire_url).status == 404
            assert page.request.get(documents_url).status == 404
            assert page.request.get(review_url).status == 404
            assert page.request.get(corrected_read_url).status == 404

            page.goto(BASE + "/local-demo/director-summary/")
            page.get_by_role("link", name="Open fictional tuition and aid planning").click()
            planning_url = page.url
            region = page.get_by_role("region", name="Regional tuition need")
            expect(region.get_by_role("link", name="HUD FY 2027")).to_be_visible()
            expect(region.get_by_text("$13,959.00", exact=True)).to_be_visible()
            page.get_by_label("Proposed award in dollars").fill("2500.00")
            page.get_by_label("Aid category").select_option(label="Enrollment")
            page.get_by_role("button", name="Project award").click()
            expect(region.get_by_text("$13,959.00", exact=True)).to_be_visible()
            expect(page.get_by_text("$22,325.00", exact=True)).to_be_visible()
            expect(page.get_by_text("$247,500.00", exact=True)).to_be_visible()
            page.screenshot(path=str(output / "director-regional-planning.png"), full_page=True)
            page.get_by_role("link", name="Back to director workload").click()
            expect(page.get_by_text("$0.00", exact=True)).to_be_visible()
            page.goto(director_a_url)
            sign_out()

            sign_in("local-demo-director-b")
            page.get_by_role("link", name=re.compile("Synthetic School B")).click()
            expect(page.locator("#draft-total")).to_have_text("0")
            assert page.request.get(director_a_url).status == 404
            assert page.request.get(case_url).status == 404
            assert page.request.get(corrected_read_url).status == 404
            assert page.request.get(planning_url).status == 404
            sign_out()

            sign_in("local-demo-family")
            page.goto(family_url)
            expect(page.locator("#selected-count")).to_have_text("2 selected")
            assert page.request.get(director_a_url).status == 404
            assert page.request.get(planning_url).status == 404
            page.goto(questionnaire_url)
            expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 3")
            expect(page.locator("#id_income-0-value")).to_have_value("765.43")
            expect(page.get_by_label("Include the example checklist?")).to_have_value("yes")
            page.goto(review_url)
            expect(page.locator("#review-status")).to_have_text("Current fictional review confirmed")
            page.goto(documents_url)
            expect(page.locator("#document-count")).to_have_text("1 listed")
            assert page.request.get(corrected_read_url).body() == corrected
            sign_out()
            context.close()
            browser.close()
        print("CUSTOMER WORKSPACE: sign-in, saved draft, financial correction, selected PDF upload, versioned readback/removal, director readback, cross-school denial and logout: PASS", flush=True)
        print("DIRECTOR PLANNING: regional need, separate award projection, unchanged saved offers and scope denials: PASS", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


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

            # The presenter guide is a manual checklist, not an authorization or
            # progress mechanism. Opening it must not select a persona.
            guide = page.locator("#presenter-guide")
            guide.locator("summary").click()
            expect(guide).to_have_attribute("open", "")
            expect(guide.get_by_role("list", name="Presenter checklist").get_by_role("listitem")).to_have_count(8)
            expect(page.locator("#authstatus")).to_have_text("Signed out")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Choose a persona")
            page.screenshot(path=str(output / "manual-presenter-guide.png"), full_page=True)
            guide.locator("summary").click()

            def summary_status(path):
                return page.evaluate("""async path => {
                    const response = await fetch(path, {
                        credentials: "same-origin", cache: "no-store"
                    });
                    return response.status;
                }""", path)

            director_url = "/local-demo/director-summary/"
            operations_url = "/local-demo/platform-operations/"
            assert summary_status(director_url) == 403, "Anonymous director report exposed"
            assert summary_status(operations_url) == 403, "Anonymous operator report exposed"

            def verify_director_report(school_name, expected, filename):
                page.get_by_role("link", name="View verified school workload").click()
                expect(page.get_by_role("heading", name="Director workload")).to_be_visible()
                expect(page.get_by_text(school_name, exact=True)).to_be_visible()
                expect(page.get_by_text("Not a live financial-aid report.")).to_be_visible()
                labels = (
                    "Draft household applications",
                    "Distinct draft households",
                    "Selected household-child links",
                    "Fictional receipts",
                    "Fictional offered-aid records",
                    "Fictional offer face value",
                )
                for label, value in zip(labels, expected, strict=True):
                    card = page.locator(".card").filter(
                        has=page.get_by_role("heading", name=label, exact=True)
                    )
                    expect(card.locator(".number")).to_have_text(value)
                page.screenshot(path=str(output / filename), full_page=True)
                page.get_by_role("link", name="Return to the fictional family walkthrough").click()

            page.get_by_role("button", name="Family applicant").click()
            expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            expect(page.locator("#school-name")).to_have_text("Synthetic Christian Academy")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("View household")
            # CROWN saved-record truth: a successful POST is not proof that
            # the annual draft was persisted. A fictional forged response must
            # never unlock child selection or duplicate POST retries.
            forged_body = '{"id":"00000000-0000-4000-8000-000000000001","status":"DRAFT"}'
            def phantom_draft(route):
                if route.request.method == "POST":
                    route.fulfill(status=200, content_type="application/json", body=forged_body)
                else:
                    route.continue_()
            page.route("**/aid-application/draft/", phantom_draft)
            page.get_by_role("button", name="Create / resume annual draft").click()
            expect(page.locator("#draft-status")).to_have_text("Verification required")
            expect(page.get_by_role("button", name="Create / resume annual draft")).to_be_disabled()
            expect(page.locator("#events")).to_contain_text("independent saved-record verification")
            # A separate GET confirms no annual draft was created. Only then
            # may the family attempt the actual write again.
            page.unroute("**/aid-application/draft/", phantom_draft)
            page.get_by_role("button", name="Refresh household").click()
            expect(page.locator("#draft-status")).to_have_text("Not created")
            expect(page.get_by_role("button", name="Create / resume annual draft")).to_be_enabled()

            # HTTP 503 after dispatch is ambiguous: the server might have
            # committed. The page may not enable an immediate duplicate POST.
            def uncertain_write(route):
                if route.request.method == "POST":
                    route.fulfill(status=503, content_type="application/json",
                                  body='{"detail":"Unavailable."}')
                else:
                    route.continue_()
            page.route("**/aid-application/draft/", uncertain_write)
            page.get_by_role("button", name="Create / resume annual draft").click()
            expect(page.locator("#draft-status")).to_have_text("Verification required")
            expect(page.get_by_role("button", name="Create / resume annual draft")).to_be_disabled()
            page.unroute("**/aid-application/draft/", uncertain_write)
            page.get_by_role("button", name="Refresh household").click()
            expect(page.locator("#draft-status")).to_have_text("Not created")
            expect(page.get_by_role("button", name="Create / resume annual draft")).to_be_enabled()

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
            # Test-only family financial shapes are validated, never stored.
            preview_result = page.get_by_role("status", name="Fictional questionnaire result")
            preview_button = page.get_by_role("button", name="Validate fictional questionnaire")
            preview_button.click()
            expect(preview_result).to_have_text(
                "Fictional income, assets and liabilities validated; no answers saved. Questionnaire incomplete."
            )
            page.get_by_label("Example scenario").select_option("fictional_moderate")
            expect(preview_result).to_be_empty()
            preview_button.click()
            expect(preview_result).to_contain_text("no answers saved")
            # Real local AES-GCM storage of a server-owned fictional PDF,
            # scoped to the family draft; never a user-provided document.
            add_document = page.get_by_role("button", name="Add fictional sample PDF")
            read_document = page.get_by_role("button", name="Read encrypted sample PDF")
            remove_document = page.get_by_role("button", name="Delete fictional sample PDF")
            document_result = page.get_by_role("status", name="Fictional document result")
            expect(add_document).to_be_enabled()
            expect(read_document).to_be_disabled()
            add_document.click()
            expect(document_result).to_contain_text(
                "Encrypted fictional sample created and independently verified."
            )
            expect(read_document).to_be_enabled()
            read_document.click()
            expect(document_result).to_contain_text("Encrypted fictional sample read and verified.")
            page.screenshot(path=str(output / "fictional-encrypted-document.png"), full_page=True)
            remove_document.click()
            expect(document_result).to_contain_text("Fictional encrypted sample deleted")
            expect(read_document).to_be_disabled()
            expect(add_document).to_be_enabled()
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
            page.locator("#synthetic-attestation").check()
            receipt_button = page.get_by_role("button", name="Record fictional receipt")
            receipt_status = page.locator("#synthetic-family-result")
            def phantom_receipt(route):
                if route.request.method == "POST":
                    route.fulfill(status=200, content_type="application/json", body=(
                        '{"application_id":"00000000-0000-4000-8000-000000000001",'
                        '"receipt_id":"00000000-0000-4000-8000-000000000002",'
                        '"consent_version":"synthetic-demo-v1","status":"SYNTHETIC_RECEIPT"}'
                    ))
                else:
                    route.continue_()
            page.route("**/synthetic/receipt/", phantom_receipt)
            receipt_button.click()
            expect(receipt_status).to_contain_text("Receipt verification required")
            expect(receipt_button).to_be_disabled()
            page.unroute("**/synthetic/receipt/", phantom_receipt)
            page.get_by_role("button", name="Refresh household").click()
            expect(receipt_button).to_be_enabled()
            def ambiguous_receipt(route):
                if route.request.method == "POST":
                    route.fulfill(status=503, content_type="application/json",
                                  body='{"detail":"Unavailable."}')
                else:
                    route.continue_()
            page.route("**/synthetic/receipt/", ambiguous_receipt)
            receipt_button.click()
            expect(receipt_status).to_contain_text("Receipt verification required")
            expect(receipt_button).to_be_disabled()
            page.unroute("**/synthetic/receipt/", ambiguous_receipt)
            page.get_by_role("button", name="Refresh household").click()
            expect(receipt_button).to_be_enabled()
            receipt_button.click()
            expect(receipt_status).to_contain_text(
                "Fictional receipt independently verified"
            )
            expect(receipt_button).to_be_disabled()
            expect(page.locator('.step[aria-current="step"]')).to_contain_text(
                "Fictional receipt"
            )
            page.wait_for_timeout(900)  # readable owner-preview pacing
            page.screenshot(path=str(output / "family-journey.png"), full_page=True)

            # Exercise PR #84's actual read-only workload API from Chromium.
            # Browser fetch preserves the current persona's session cookies.
            config = page.evaluate("""async () => {
                const response = await fetch("/local-demo/config/", {credentials: "same-origin"});
                if (!response.ok) throw new Error("Synthetic config unavailable");
                return response.json();
            }""")
            school_a, school_b = config["school_a"], config["school_b"]
            def workload(school):
                url = (
                    f"/api/v1/schools/{school['id']}/academic-years/"
                    f"{school['year_id']}/aid-applications/draft-workload/"
                )
                return page.evaluate("""async url => {
                    const response = await fetch(url, {credentials: "same-origin"});
                    return {
                        status: response.status,
                        cacheControl: response.headers.get("Cache-Control") || "",
                        data: await response.json()
                    };
                }""", url)

            family_workload = workload(school_a)
            assert family_workload["status"] == 404, "Family must not see staff workload"
            assert family_workload["data"] == {"detail": "Not found."}
            assert summary_status(director_url) == 404, "Family saw a director report"
            assert summary_status(operations_url) == 403, "Family saw an operator report"

            page.get_by_role("button", name="School A director").click()
            expect(page.locator("#application-count")).to_have_text("1")
            school_a_workload = workload(school_a)
            assert school_a_workload["status"] == 200, "Authorized director workload denied"
            assert school_a_workload["data"] == {
                "school_id": school_a["id"],
                "academic_year_id": school_a["year_id"],
                "draft_application_records": 1,
                "distinct_draft_households": 1,
                "selected_household_student_links": 2,
                "application_unit": "household_application_not_student",
                "selection_unit": "household_student_link_not_distinct_student",
                "financial_submissions_or_awards_included": False,
            }, "Director workload count/units differ from saved synthetic drafts"
            assert "no-store" in school_a_workload["cacheControl"].lower()
            assert workload(school_b)["status"] == 404, "Director A saw School B workload"
            print("CHROMIUM WORKLOAD A: family denied, director scoped, count 1/1/2, cross-school denied", flush=True)
            assert summary_status(operations_url) == 403, "Director saw an operator report"
            verify_director_report(
                "Synthetic Christian Academy", ("1", "1", "2", "1", "0", "$0.00"),
                "director-workload-before-offer.png",
            )

            # Returning to the walkthrough clears browser state, not the
            # authenticated server session. A failed logout must not permit
            # another login or expose any stale persona panel.
            assert summary_status(director_url) == 200
            login_posts = []
            def observe_login(route):
                if route.request.method == "POST":
                    login_posts.append(True)
                route.continue_()

            def unavailable_logout(route):
                route.fulfill(status=503, content_type="application/json",
                              body='{"detail":"Unavailable."}')

            page.route("**/test-auth/login/", observe_login)
            page.route("**/test-auth/logout/", unavailable_logout)
            page.get_by_role("button", name="School A director").click()
            expect(page.locator("#authstatus")).to_have_text("Session not verified")
            expect(page.locator("#director")).to_be_hidden()
            expect(page.locator("#family")).to_be_hidden()
            expect(page.locator("#operator")).to_be_hidden()
            assert not login_posts, "Sign-in attempted despite unverified logout"
            page.unroute("**/test-auth/logout/", unavailable_logout)
            page.unroute("**/test-auth/login/", observe_login)
            page.get_by_role("button", name="School A director").click()
            expect(page.locator("#application-count")).to_have_text("1")
            page.get_by_role("button", name="View selected children").click()
            expect(page.locator("#case-detail")).to_contain_text("selected children: 2")
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Director review")
            assessment_button = page.get_by_role("button", name="Preview fictional assessment")
            assessment_result = page.get_by_role("status", name="Fictional assessment result")
            assessment_buckets = page.get_by_role("list", name="Fictional bucket recommendations")

            def missing_assessment_total(route):
                response = route.fetch()
                assert response.ok, "Expected a valid assessment before altering the response"
                payload = response.json()
                del payload["total_recommendation_cents"]
                route.fulfill(response=response, json=payload)

            assessment_path = "**/synthetic/assessment/*/"
            page.route(assessment_path, missing_assessment_total)
            assessment_button.click()
            expect(assessment_result).to_have_text("Fictional assessment unavailable.")
            expect(assessment_buckets).to_be_hidden()
            page.unroute(assessment_path, missing_assessment_total)
            assessment_button.click()
            expect(assessment_result).to_contain_text("Fictional preview total: $92.00")
            expect(assessment_buckets).to_contain_text("hardship: $50.00 (test cap applied)")
            page.get_by_label("Fictional scenario").select_option("fictional_moderate")
            expect(assessment_result).to_be_empty()
            assessment_button.click()
            expect(assessment_result).to_contain_text("Fictional preview total: $159.67")
            offer_button = page.get_by_role("button", name="Record fictional $250 need offer")
            def phantom_offer(route):
                if route.request.method == "POST":
                    route.fulfill(status=200, content_type="application/json", body=(
                        '{"application_id":"00000000-0000-4000-8000-000000000001",'
                        '"student_id":"00000000-0000-4000-8000-000000000002",'
                        '"bucket":"need","amount_cents":25000,"status":"SYNTHETIC_OFFERED"}'
                    ))
                else:
                    route.continue_()
            page.route("**/synthetic/offers/*/", phantom_offer)
            offer_button.click()
            expect(page.locator("#case-detail")).to_contain_text(
                "Offer verification required"
            )
            expect(offer_button).to_be_disabled()
            page.unroute("**/synthetic/offers/*/", phantom_offer)
            page.get_by_role("button", name="View selected children").click()
            offer_button = page.get_by_role("button", name="Record fictional $250 need offer")
            expect(offer_button).to_be_enabled()
            def ambiguous_offer(route):
                if route.request.method == "POST":
                    route.fulfill(status=503, content_type="application/json",
                                  body='{"detail":"Unavailable."}')
                else:
                    route.continue_()
            page.route("**/synthetic/offers/*/", ambiguous_offer)
            offer_button.click()
            expect(page.locator("#case-detail")).to_contain_text("Offer verification required")
            expect(offer_button).to_be_disabled()
            page.unroute("**/synthetic/offers/*/", ambiguous_offer)
            page.get_by_role("button", name="View selected children").click()
            offer_button = page.get_by_role("button", name="Record fictional $250 need offer")
            expect(offer_button).to_be_enabled()
            offer_button.click()
            expect(page.locator("#case-detail")).to_contain_text(
                "Fictional $250 need offer independently verified"
            )
            expect(page.locator('.step[aria-current="step"]')).to_contain_text(
                "Fictional $250 offer"
            )
            page.wait_for_timeout(900)  # readable owner-preview pacing
            page.get_by_role("button", name="Verify other school is denied").click()
            expect(page.locator("#events")).to_contain_text(
                "PASS: Another school's director inventory denied (404)"
            )
            page.screenshot(path=str(output / "director-journey.png"), full_page=True)
            verify_director_report(
                "Synthetic Christian Academy", ("1", "1", "2", "1", "1", "$250.00"),
                "director-workload-after-offer.png",
            )
            page.get_by_role("button", name="Family applicant").click()
            expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            page.get_by_role("button", name="Read fictional offered aid").click()
            offer_status = page.get_by_role("status", name="Fictional offered aid result")
            expect(offer_status).to_contain_text(
                "Fictional offered aid: $250.00 need"
            )
            expect(offer_status).to_contain_text(
                "not a payment or binding award"
            )
            expect(page.locator('.step[aria-current="step"]')).to_contain_text(
                "Fictional $250 offer"
            )
            page.wait_for_timeout(900)  # readable owner-preview pacing
            page.screenshot(path=str(output / "family-offer-readback.png"), full_page=True)

            page.get_by_role("button", name="School B director").click()
            expect(page.locator("#application-count")).to_have_text("0")
            expect(page.locator("#synthetic-offer-result")).to_be_empty()
            school_b_workload = workload(school_b)
            assert school_b_workload["status"] == 200, "School B director workload denied"
            assert school_b_workload["data"]["draft_application_records"] == 0
            assert school_b_workload["data"]["distinct_draft_households"] == 0
            assert school_b_workload["data"]["selected_household_student_links"] == 0
            assert school_b_workload["data"]["financial_submissions_or_awards_included"] is False
            assert workload(school_a)["status"] == 404, "Director B saw School A workload"
            print("CHROMIUM WORKLOAD B: empty school 0/0/0, cross-school denied", flush=True)
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Director review")
            page.get_by_role("button", name="Verify other school is denied").click()
            expect(page.locator("#events")).to_contain_text(
                "PASS: Another school's director inventory denied (404)"
            )
            page.screenshot(path=str(output / "other-school-journey.png"), full_page=True)
            verify_director_report(
                "Synthetic School B", ("0", "0", "0", "0", "0", "$0.00"),
                "director-workload-school-b.png",
            )
            page.get_by_role("button", name="Arete platform operator").click()
            expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            expect(page.locator("#operator")).to_be_visible()
            assert summary_status(director_url) == 404, "Operator saw a school director report"
            page.locator("#operator-summary-link").click()
            expect(page.get_by_role("heading", name="School readiness overview")).to_be_visible()
            expect(page.locator('table[aria-label="Saved synthetic school inventory"] tbody tr')).to_have_count(2)
            expect(page.get_by_text("Not a provisioning system.")).to_be_visible()
            expect(page.get_by_text("Synthetic Christian Academy")).to_be_visible()
            expect(page.get_by_text("Synthetic School B")).to_be_visible()
            inventory = page.get_by_role("table", name="Saved synthetic school inventory")
            for school_name in ("Synthetic Christian Academy", "Synthetic School B"):
                row = inventory.get_by_role("row").filter(has_text=school_name)
                expect(row.get_by_role("cell", name="2026-27", exact=True)).to_be_visible()
                expect(row.get_by_role("cell", name="Fictional seed only", exact=True)).to_be_visible()
                expect(row.get_by_role("cell", name="Not configured", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="School preparation status")).to_be_visible()
            expect(page.get_by_text("No preparation receipts have been recorded.")).to_be_visible()
            preparation = page.get_by_role("table", name="Saved fictional preparation status")
            expect(preparation.locator("tbody tr")).to_have_count(5)
            expect(preparation.locator("tbody td")).to_have_text(["0"] * 5)
            page.screenshot(path=str(output / "platform-operations-preview.png"), full_page=True)
            print("CHROMIUM OPERATIONS: two saved fictional schools; no receipts or provisioning", flush=True)
            page.get_by_role("link", name="Return to the fictional walkthrough").click()
            pending_receipts = []
            receipt_readback = "**/synthetic/receipt/read/"

            def hold_receipt(route):
                pending_receipts.append(route)

            page.route(receipt_readback, hold_receipt)
            with page.expect_request(receipt_readback):
                page.get_by_role("button", name="Family applicant").click()
                expect(page.locator("#authstatus")).to_have_text("Synthetic session active")
            page.get_by_role("button", name="Read fictional offered aid").click()
            saved_offer = page.get_by_text("Fictional offered aid: $250.00 need")
            expect(saved_offer).to_be_visible()
            assert len(pending_receipts) == 1, "Expected one pending receipt readback"
            pending_receipts.pop().continue_()
            page.unroute(receipt_readback, hold_receipt)
            expect(page.locator("#synthetic-family-result")).to_have_text(
                "Fictional receipt independently verified. Application remains DRAFT."
            )
            expect(saved_offer).to_be_visible()
            expect(page.locator('.step[aria-current="step"]')).to_contain_text("Fictional $250 offer")
            print("CHROMIUM NAVIGATION: failed logout denies sign-in; dashboard and operator return verified", flush=True)
            context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    verify_customer_workspace(sync_playwright, expect, output, runner)
    print("Browser demo passed. Synthetic-only screenshots and video:", output)


if __name__ == "__main__":
    main()
