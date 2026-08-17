"""
LibGuide Usage-Report Zip Uploader

Uploads the per-library usage-report zips produced by `create_usage_zips.py`
into their matching boxes on the "Datasets" LibGuide, via Selenium (LibApps
interactive login + MFA -- there is no REST upload path).

Two modes:
  --discover : log in, scrape every box (title + box_id) and write
               `libguide-boxes.csv` for review. Run this first.
  (default)  : read `libguide-boxes.csv`, map each zip to its box, and upload
               each zip through the box's "Add Document / File" dialog.

The box title equals the library_name in `libinsight-platforms.csv`; the first
upload box, "BCLA Platform Summaries", takes the `bcla_summaries` zip under a
special title. The "BCLA Members" box is skipped.

Login/driver/logging helpers mirror `sushi_harvest_tracker.py`.
"""

import argparse
import csv
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

# ============================================================================
# CONFIGURATION
# ============================================================================


def setup_logging():
    """
    Create the logs directory and mirror stdout/stderr to a timestamped log file.

    Returns:
        The path to the log file that was created.
    """
    os.makedirs("logs", exist_ok=True)
    log_filename = datetime.now().strftime("logs/upload_zip_%Y%m%d_%H%M%S.log")

    class Tee:
        """File-like object that writes to several underlying streams at once."""

        def __init__(self, *files):
            self.files = files

        def write(self, obj):
            """Write to every underlying stream and flush immediately."""
            for f in self.files:
                f.write(obj)
                f.flush()

        def flush(self):
            """Flush every underlying stream."""
            for f in self.files:
                f.flush()

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    # Kept open for the lifetime of the process so it can capture all output.
    log_file = open(log_filename, "w", encoding="utf-8")  # pylint: disable=consider-using-with

    sys.stdout = Tee(orig_stdout, log_file)
    sys.stderr = Tee(orig_stderr, log_file)

    print(f"Logging to: {log_filename}")
    return log_filename


LOG_FILENAME = setup_logging()
load_dotenv()

# LibApps / LibGuides
LIBAPPS_BASE_URL = "https://acaweb.libapps.com"
GUIDE_ID = 1423983
GUIDE_URL = f"{LIBAPPS_BASE_URL}/libguides/admin_c.php?g={GUIDE_ID}"

# Fiscal-year tokens -- bump both each year.
FISCAL_YEAR_SHORT = "2526"        # used in zip names and the combined title
FISCAL_YEAR_LONG = "2025-26"      # used in the human-readable description

# Zip naming produced by create_usage_zips.py: "<subdir>_<FY>_stats.zip"
ZIP_STEM_SUFFIX = f"_{FISCAL_YEAR_SHORT}_stats"
ZIP_GLOB = f"*{ZIP_STEM_SUFFIX}.zip"

# The BCLA summaries subdirectory / box are special-cased.
BCLA_SUBDIR = "bcla_summaries"
BCLA_BOX_TITLE = "BCLA Platform Summaries"
BCLA_DOC_TITLE = f"{FISCAL_YEAR_SHORT}_combined_stats"

# Boxes that are never upload targets.
SKIP_BOX_IDS = {"33253492", "33283351"}          # "BCLA Members"
SKIP_BOX_TITLES = {"BCLA Members", "space"}

DEFAULT_ZIPS_DIR = "usage_reports"
DEFAULT_BOXES_CSV = "libguide-boxes.csv"
DEFAULT_PLATFORMS_CSV = "libinsight-platforms.csv"


@dataclass
class UploadJob:
    """A single zip to upload, already resolved to its target box and metadata."""

    box_id: str
    box_title: str
    zip_path: Path
    doc_title: str
    description: str


# ============================================================================
# SHARED SELENIUM HELPERS (mirrors sushi_harvest_tracker.py)
# ============================================================================


def setup_chrome_driver():
    """Set up and return a configured Chrome WebDriver."""
    print("Setting up Chrome driver...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=chrome_options)


def get_credentials():
    """
    Load LibApps credentials from the environment.

    Returns:
        Tuple of (username, password), or (None, None) if not available.
    """
    username = os.getenv("LA_USER")
    password = os.getenv("LA_PASS")
    if not username or not password:
        print("\n✗ Error: Could not load credentials from .env file")
        print("Please make sure you have a .env file with LA_USER and LA_PASS")
        return None, None
    return username, password


def login_to_libapps(driver, username, password, mfa_code):
    """
    Authenticate for the LibGuide by navigating to GUIDE_URL and logging in on
    the LibApps login page it redirects to. Logging in through the guide URL
    (rather than a LibInsight-scoped login.php entry point) ensures the resulting
    session authorizes the LibGuides admin pages. Mirrors the field IDs used by
    sushi_harvest_tracker.login_to_libinsight.
    """
    print("\nLogging into LibApps (via the guide URL)...")
    driver.get(GUIDE_URL)

    try:
        # If we are already authenticated, the login form will not appear.
        try:
            username_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "s-libapps-email"))
            )
        except TimeoutException:
            print("  → No login form shown; appears already authenticated.")
            username_field = None

        if username_field is not None:
            username_field.send_keys(username)
            print("✓ Username entered")

            password_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "s-libapps-password"))
            )
            password_field.send_keys(password)
            print("✓ Password entered")

            driver.find_element(By.ID, "s-libapps-login-button").click()
            time.sleep(2)

            mfa_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "s-libapps-code"))
            )
            mfa_field.send_keys(mfa_code)
            print("✓ MFA code entered")

            driver.find_element(By.ID, "s-libapps-mfa-button").click()
            time.sleep(3)

        # Land squarely on the guide regardless of the login's redirect target,
        # and confirm we are authenticated by waiting for a box to render.
        driver.get(GUIDE_URL)
        print(f"  → Current URL after login: {driver.current_url}")
        if "login" in driver.current_url.lower():
            raise RuntimeError("Login failed - still on the login page")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[id^='s-lg-box-']"))
        )
        print("✓ Login successful - guide loaded!")

    except TimeoutException:
        print("✗ Error: Login/guide elements not found. Check the page structure.")
        raise
    except WebDriverException as e:
        print(f"✗ Error during login: {e}")
        raise


def click_with_fallbacks(driver, element):
    """Try several strategies to click an element. Returns True if one succeeds."""
    try:
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(element))
        element.click()
        return True
    except WebDriverException:
        pass

    try:
        ActionChains(driver).move_to_element(element).click().perform()
        return True
    except WebDriverException:
        pass

    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except WebDriverException:
        return False


# ============================================================================
# GUIDE NAVIGATION / SCRAPING
# ============================================================================


def _normalize(text):
    """Collapse all runs of whitespace to single spaces and strip."""
    return " ".join((text or "").split())


def open_guide(driver):
    """Navigate to the guide edit page and wait for its boxes to render."""
    driver.get(GUIDE_URL)
    if "login" in driver.current_url.lower():
        raise RuntimeError("Not authenticated for the guide (redirected to login)")
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div[id^='s-lg-box-']"))
    )


def _box_title_text(driver, box_el):
    """Return the box's title text only (excluding the edit/delete button text)."""
    try:
        heading = box_el.find_element(By.CSS_SELECTOR, "h2.s-lib-box-title")
    except NoSuchElementException:
        return ""
    raw = driver.execute_script(
        "let t='';for(const n of arguments[0].childNodes)"
        "{if(n.nodeType===3)t+=n.textContent;}return t;",
        heading,
    )
    return _normalize(raw)


def discover_boxes(driver):
    """
    Scrape every box on the guide.

    Returns:
        List of (title, box_id) tuples, excluding the skipped boxes.
    """
    rows = []
    for box in driver.find_elements(By.CSS_SELECTOR, "div[id^='s-lg-box-']"):
        box_id = (box.get_attribute("id") or "").replace("s-lg-box-", "", 1)
        if not box_id.isdigit():
            continue  # e.g. the "s-lg-box-collapse-<id>" content containers
        title = _box_title_text(driver, box)
        if not title or box_id in SKIP_BOX_IDS or title in SKIP_BOX_TITLES:
            print(f"  → skipping box #{box_id} ('{title}')")
            continue
        rows.append((title, box_id))
    return rows


def write_boxes_csv(rows, boxes_csv):
    """Write discovered boxes to a review CSV (library_name, box_id)."""
    with open(boxes_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["library_name", "box_id"])
        writer.writerows(rows)
    print(f"\n✓ Wrote {len(rows)} boxes to {boxes_csv}")
    print("  Review it (fix any title mismatches) before running an upload.")


def box_contains_title(driver, box_id, doc_title):
    """Return True if the box already has a content link whose text == doc_title."""
    try:
        box = driver.find_element(By.ID, f"s-lg-box-{box_id}")
    except NoSuchElementException:
        return False
    links = box.find_elements(By.CSS_SELECTOR, "ul.s-lg-link-list a")
    return any(_normalize(link.text) == doc_title for link in links)


# ============================================================================
# UPLOAD FLOW
# ============================================================================


def open_add_document_modal(driver, box_id):
    """Open the "Add Document / File" dialog for a box and confirm its context."""
    box = driver.find_element(By.ID, f"s-lg-box-{box_id}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)

    toggle = box.find_element(
        By.XPATH, ".//button[@data-toggle='dropdown'][contains(., 'Add / Reorder')]"
    )
    click_with_fallbacks(driver, toggle)

    doc_link = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((
            By.XPATH,
            (
                f"//div[@id='s-lg-box-{box_id}']//ul[contains(@class,'s-lg-add-content-drop')]"
                "//a[normalize-space(.)='Document / File']"
            ),
        ))
    )
    click_with_fallbacks(driver, doc_link)

    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "doc_title")))
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "file_upload")))

    # Safety guard: the modal's hidden box_id must match the box we intended.
    modal_box_id = _normalize(
        driver.find_element(By.ID, "box_id").get_attribute("textContent")
    )
    if modal_box_id != str(box_id):
        raise RuntimeError(
            f"Modal opened for box {modal_box_id}, expected {box_id} - aborting upload"
        )


def fill_document_form(driver, job):
    """Populate the Add Document / File form fields for one job."""
    title_field = driver.find_element(By.ID, "doc_title")
    title_field.clear()
    title_field.send_keys(job.doc_title)

    desc_field = driver.find_element(By.ID, "description")
    desc_field.clear()
    desc_field.send_keys(job.description)

    Select(driver.find_element(By.NAME, "desc_pos")).select_by_value("1")  # Beneath title
    driver.find_element(By.ID, "file_upload").send_keys(str(job.zip_path.resolve()))
    Select(driver.find_element(By.ID, "pos_after_idx")).select_by_value("0")  # Top of box


def close_modal(driver):
    """Dismiss the dialog without saving (used for dry-run)."""
    try:
        cancel = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'ui-dialog-buttonset')]//button[normalize-space(.)='Cancel']",
        )
        click_with_fallbacks(driver, cancel)
        return
    except NoSuchElementException:
        pass
    try:
        driver.find_element(By.CSS_SELECTOR, ".ui-dialog-titlebar-close").click()
    except NoSuchElementException:
        pass


def _wait_for_document(driver, box_id, doc_title):
    """After saving, confirm the new document appears in the box (retries with reload)."""
    try:
        WebDriverWait(driver, 20).until(
            EC.invisibility_of_element_located((By.ID, "s-lib-alert"))
        )
    except TimeoutException:
        messages = [
            el.text.strip()
            for el in driver.find_elements(By.CSS_SELECTOR, "#s-lib-alert .s-lib-form-msg")
            if el.text.strip()
        ]
        print(f"   ✗ modal did not close; form messages: {messages}")
        close_modal(driver)
        return False

    for _ in range(3):
        driver.get(GUIDE_URL)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, f"s-lg-box-{box_id}"))
            )
        except TimeoutException:
            return False
        if box_contains_title(driver, box_id, doc_title):
            return True
        time.sleep(2)
    return False


def _do_upload(driver, job):
    """Fill, save, and verify one upload once its modal is open."""
    try:
        fill_document_form(driver, job)
        click_with_fallbacks(driver, driver.find_element(By.ID, "s-lib-alert-btn-first"))
    except WebDriverException as exc:
        print(f"   ✗ upload failed: {exc}")
        driver.save_screenshot(f"debug_upload_{job.box_id}.png")
        return "error"

    if _wait_for_document(driver, job.box_id, job.doc_title):
        print("   ✓ uploaded and verified")
        return "uploaded"

    print("   ⚠ save submitted but entry not verified - check manually")
    driver.save_screenshot(f"debug_verify_{job.box_id}.png")
    return "unverified"


def upload_job(driver, job, dry_run):
    """
    Process a single upload job end to end.

    Returns one of: "uploaded", "skipped", "dry-run", "unverified", "error".
    """
    print(
        f"\n📦 {job.zip_path.name} → box '{job.box_title}' (#{job.box_id}) "
        f"as '{job.doc_title}'"
    )
    if not job.zip_path.exists():
        print("   ✗ zip file not found - skipping")
        return "error"

    open_guide(driver)  # fresh DOM each job
    if box_contains_title(driver, job.box_id, job.doc_title):
        print("   ⏭  a file with this title already exists in the box - skipping")
        return "skipped"

    try:
        open_add_document_modal(driver, job.box_id)
    except (TimeoutException, WebDriverException, RuntimeError) as exc:
        print(f"   ✗ could not open the Add Document / File dialog: {exc}")
        return "error"

    if dry_run:
        located = bool(driver.find_elements(By.ID, "file_upload")) and bool(
            driver.find_elements(By.ID, "s-lib-alert-btn-first")
        )
        close_modal(driver)
        print(
            "   ✓ dry-run: file input + Save button located, not submitting"
            if located
            else "   ✗ dry-run: expected controls not found"
        )
        return "dry-run"

    return _do_upload(driver, job)


# ============================================================================
# JOB BUILDING
# ============================================================================


def load_box_map(boxes_csv):
    """Load libguide-boxes.csv into a {box_title: box_id} dict."""
    mapping = {}
    with open(boxes_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            title = _normalize(row.get("library_name", ""))
            box_id = (row.get("box_id", "") or "").strip()
            if title and box_id:
                mapping[title] = box_id
    return mapping


def load_library_names(platforms_csv):
    """Load libinsight-platforms.csv into a {abbrev: library_name} dict."""
    mapping = {}
    with open(platforms_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            abbrev = (row.get("library_abbreviation", "") or "").strip().lower()
            name = _normalize(row.get("library_name", ""))
            if abbrev and name and abbrev not in mapping:
                mapping[abbrev] = name
    return mapping


def _resolve_titles(abbrev, abbrev_to_name):
    """
    Map a zip's abbreviation to (box_title, doc_title, description).

    Returns None if the abbreviation has no known library box.
    """
    if abbrev == BCLA_SUBDIR:
        return (
            BCLA_BOX_TITLE,
            BCLA_DOC_TITLE,
            f"Combined usage statistics for BCLA Core Vendors, FY {FISCAL_YEAR_LONG}",
        )
    library_name = abbrev_to_name.get(abbrev)
    if not library_name:
        return None
    return (
        library_name,
        f"{abbrev}{ZIP_STEM_SUFFIX}",
        f"{library_name} usage statistics for BCLA Core Vendors, FY {FISCAL_YEAR_LONG}",
    )


def build_jobs(zip_paths, box_map, abbrev_to_name):
    """
    Turn zip paths into resolved UploadJobs.

    Returns:
        Tuple of (jobs, unresolved) where unresolved is a list of
        (zip_name, reason) strings for zips that could not be matched.
    """
    jobs = []
    unresolved = []
    for zip_path in zip_paths:
        stem = zip_path.stem
        if not stem.endswith(ZIP_STEM_SUFFIX):
            unresolved.append((zip_path.name, "name does not match *_<FY>_stats.zip"))
            continue
        abbrev = stem[: -len(ZIP_STEM_SUFFIX)]
        titles = _resolve_titles(abbrev, abbrev_to_name)
        if titles is None:
            unresolved.append((zip_path.name, f"no library box for abbrev '{abbrev}'"))
            continue
        box_title, doc_title, description = titles
        box_id = box_map.get(box_title)
        if not box_id:
            unresolved.append((zip_path.name, f"box '{box_title}' not in boxes CSV"))
            continue
        jobs.append(UploadJob(box_id, box_title, zip_path, doc_title, description))
    return jobs, unresolved


def find_zips(zips_dir, library):
    """Find candidate zips, optionally filtered to a single abbreviation."""
    directory = Path(zips_dir)
    if not directory.is_dir():
        return []
    if library:
        candidate = directory / f"{library}{ZIP_STEM_SUFFIX}.zip"
        return [candidate] if candidate.exists() else []
    return sorted(directory.glob(ZIP_GLOB))


# ============================================================================
# MAIN
# ============================================================================


def parse_arguments():
    """Build the argument parser and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Upload usage-report zips into their LibGuide boxes."
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Scrape the guide's boxes and write the review CSV, then exit.",
    )
    parser.add_argument(
        "--zips-dir",
        default=DEFAULT_ZIPS_DIR,
        help=f"Directory holding the zip files (default: {DEFAULT_ZIPS_DIR}).",
    )
    parser.add_argument(
        "--library",
        help="Only process this abbreviation's zip (e.g. 'alc', 'bcla_summaries').",
    )
    parser.add_argument(
        "--boxes-csv",
        default=DEFAULT_BOXES_CSV,
        help=f"Box mapping CSV from --discover (default: {DEFAULT_BOXES_CSV}).",
    )
    parser.add_argument(
        "--platforms-csv",
        default=DEFAULT_PLATFORMS_CSV,
        help=f"Platforms CSV for abbrev→library_name (default: {DEFAULT_PLATFORMS_CSV}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Open each Add Document dialog and confirm controls, but do not submit.",
    )
    return parser.parse_args()


def run_discover(driver, args):
    """Discovery mode: scrape boxes and write the review CSV."""
    print("\n🔍 DISCOVER MODE: scraping guide boxes...")
    rows = discover_boxes(driver)
    write_boxes_csv(rows, args.boxes_csv)


def run_uploads(driver, args):
    """Upload mode: resolve zips to boxes and upload each."""
    if not Path(args.boxes_csv).exists():
        print(f"\n✗ {args.boxes_csv} not found. Run with --discover first.")
        return

    box_map = load_box_map(args.boxes_csv)
    abbrev_to_name = load_library_names(args.platforms_csv)
    zip_paths = find_zips(args.zips_dir, args.library)

    if not zip_paths:
        print(f"\n⚠  No matching zips found in '{args.zips_dir}'. Nothing to do.")
        return

    jobs, unresolved = build_jobs(zip_paths, box_map, abbrev_to_name)
    for name, reason in unresolved:
        print(f"  ⚠  unmatched zip {name}: {reason}")

    mode = "DRY-RUN" if args.dry_run else "UPLOAD"
    print(f"\n▶  {mode}: {len(jobs)} zip(s) resolved to boxes")

    tally = {}
    for job in jobs:
        status = upload_job(driver, job, args.dry_run)
        tally[status] = tally.get(status, 0) + 1
        time.sleep(1)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for status, count in sorted(tally.items()):
        print(f"  {status}: {count}")


def main():
    """Main script execution."""
    args = parse_arguments()

    print("=" * 70)
    print("LibGuide Usage-Report Zip Uploader")
    print(f"\n📄 Log file: {LOG_FILENAME}")
    print(f"   Guide: {GUIDE_URL}")
    print("=" * 70)

    username, password = get_credentials()
    if not username or not password:
        return
    mfa_code = input("Google Authenticator MFA code: ")

    driver = None
    try:
        driver = setup_chrome_driver()
        login_to_libapps(driver, username, password, mfa_code)
        open_guide(driver)

        if args.discover:
            run_discover(driver, args)
        else:
            run_uploads(driver, args)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"\n✗ Fatal error: {exc}")
        traceback.print_exc()

    finally:
        if driver:
            print("\nClosing browser...")
            time.sleep(2)
            driver.quit()
            print("✓ Browser closed")


if __name__ == "__main__":
    main()
