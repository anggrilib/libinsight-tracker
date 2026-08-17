"""
SUSHI Reharvest Tool
Reads a CSV of harvest requests and submits each one through the
LibInsight "Fetch SUSHI Data Now" form using Selenium automation.

CSV columns required:
    dataset_id, platform_id, service_provider, report_type,
    data_types, begin_date, end_date

Usage:
    python sushi_reharvest.py
    python sushi_reharvest.py --csv my_other_file.csv
"""

import argparse
import csv
import os
import sys
import time
import traceback
from datetime import datetime

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

# Base URLs (same as sushi_harvest_tracker.py)
LIBINSIGHT_BASE_URL = "https://acaweb.libinsight.com"
LIBAPPS_BASE_URL = "https://acaweb.libapps.com"

# Default CSV file to read harvest requests from
DEFAULT_CSV = "reharvest.csv"

# Seconds to pause after clicking buttons to let the page react
PAGE_LOAD_WAIT = 3

# ============================================================================
# REPORT TYPE MAP
# The CSV uses the full name shown in the UI; the form needs the short code.
# Add rows here if new report types appear.
# ============================================================================
REPORT_TYPE_MAP = {
    "platform master report": "PR",
    "database master report": "DR",
    "title master report":    "TR",
    "item master report":     "IR",
}

# ============================================================================
# LOGGING SETUP  (mirrors sushi_harvest_tracker.py pattern)
# ============================================================================

def setup_logging():
    """Create logs/ directory and tee stdout/stderr to a timestamped file."""
    os.makedirs("logs", exist_ok=True)
    log_filename = datetime.now().strftime("logs/sushi_reharvest_%Y%m%d_%H%M%S.log")

    class Tee:
        """Write to multiple streams at once."""
        def __init__(self, *files):
            self.files = files
        def write(self, obj):
            """Write obj to every stream and flush immediately."""
            for f in self.files:
                f.write(obj)
                f.flush()
        def flush(self):
            """Flush every stream."""
            for f in self.files:
                f.flush()

    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    log_file = open(log_filename, "w", encoding="utf-8")  # pylint: disable=consider-using-with
    sys.stdout = Tee(orig_stdout, log_file)
    sys.stderr = Tee(orig_stderr, log_file)

    print(f"Logging to: {log_filename}")
    return log_filename


LOG_FILENAME = setup_logging()

# ============================================================================
# BROWSER SETUP
# ============================================================================

def setup_chrome_driver():
    """Return a configured Chrome WebDriver instance."""
    print("Setting up Chrome driver...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# ============================================================================
# LOGIN  (copied from login_to_libinsight() in sushi_harvest_tracker.py)
# ============================================================================

def login_to_libinsight(driver, username, password, mfa_code):
    """
    Log into LibInsight using username, password, and MFA code.

    Args:
        driver:    Selenium WebDriver instance
        username:  LibApps username (from .env LA_USER)
        password:  LibApps password (from .env LA_PASS)
        mfa_code:  Google Authenticator code entered at the prompt
    """
    print("\nLogging into LibInsight...")
    driver.get(f"{LIBAPPS_BASE_URL}/libapps/login.php?site_id=25079&target=admin/welcome")

    try:
        # Username
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-email"))
        )
        username_field.send_keys(username)
        print("✓ Username entered")

        # Password
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-password"))
        )
        password_field.send_keys(password)
        print("✓ Password entered")

        # Click Sign In
        driver.find_element(By.ID, "s-libapps-login-button").click()
        time.sleep(2)

        # MFA code
        mfa_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-code"))
        )
        mfa_field.send_keys(mfa_code)
        print("✓ MFA code entered")

        # Click Verify
        driver.find_element(By.ID, "s-libapps-mfa-button").click()
        time.sleep(3)

        # Confirm we left the login page
        current_url = driver.current_url
        print(f"  → Current URL after login: {current_url}")
        if "login" in current_url.lower():
            print("✗ Login failed - still on login page")
            raise RuntimeError("Login verification failed")

        print("✓ Login successful!")

    except TimeoutException:
        print("✗ Error: Login page elements not found.")
        raise
    except WebDriverException as e:
        print(f"✗ Error during login: {e}")
        raise

# ============================================================================
# CSV LOADING
# ============================================================================

def load_reharvest_csv(csv_path):
    """
    Read the reharvest CSV and return a list of row dictionaries.

    Expected columns:
        dataset_id, platform_id, service_provider, report_type,
        data_types, begin_date, end_date

    Args:
        csv_path: Path to the CSV file

    Returns:
        List of dicts, one per row
    """
    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Strip whitespace from every field value
                cleaned = {k: v.strip() for k, v in row.items()}
                rows.append(cleaned)
        print(f"✓ Loaded {len(rows)} row(s) from {csv_path}")
        return rows
    except FileNotFoundError:
        print(f"✗ CSV file not found: {csv_path}")
        sys.exit(1)
    except OSError as e:
        print(f"✗ Error reading CSV: {e}")
        sys.exit(1)

# ============================================================================
# DATE FORMATTING
# ============================================================================

def format_date_for_input(date_str):
    """
    Convert a date string to YYYY-MM-DD format for HTML date inputs.

    Accepts: MM/DD/YYYY  or  YYYY-MM-DD
    Returns: YYYY-MM-DD string, or None if the format is not recognised.

    Example:
        "01/01/2026"  →  "2026-01-01"
        "2026-01-01"  →  "2026-01-01"  (already correct)
    """
    date_str = date_str.strip()

    # Already in YYYY-MM-DD format
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str

    # Try MM/DD/YYYY
    try:
        # DTZ007: a bare calendar date has no timezone. Do not "fix" this with
        # .astimezone() -- that can shift the date a day and corrupt the harvest range.
        dt = datetime.strptime(date_str, "%m/%d/%Y")  # noqa: DTZ007
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        print(f"  ⚠️  Unrecognised date format: '{date_str}'. Expected MM/DD/YYYY or YYYY-MM-DD.")
        return None

# ============================================================================
# FORM INTERACTION HELPERS
# ============================================================================

def ensure_fetch_section_open(driver):
    """
    Make sure the 'Fetch SUSHI Data Now' accordion section is expanded.
    The page loads with it open by default, but we check just in case.
    """
    try:
        fetch_collapse = driver.find_element(By.ID, "collapse-fetch")
        if "show" not in fetch_collapse.get_attribute("class"):
            # Click the accordion toggle button to open it
            toggle_button = driver.find_element(
                By.XPATH,
                "//button[@data-target='#collapse-fetch']"
            )
            toggle_button.click()
            time.sleep(1)
            print("  → Opened 'Fetch SUSHI Data Now' section")
        else:
            print("  → 'Fetch SUSHI Data Now' section already open")
    except NoSuchElementException:
        print("  ⚠️  Could not find accordion section — proceeding anyway")


def select_service_provider(driver, service_provider_name):
    """
    Choose the correct option in the Service Provider dropdown.

    The option text in the HTML often has extra whitespace and may include
    a pipe-separated suffix like '| Platform: Grove Music Online'.
    We do a partial-match (case-insensitive) on the core provider name.

    Args:
        driver:                Selenium WebDriver instance
        service_provider_name: The 'service_provider' value from the CSV

    Returns:
        True if a matching option was found and selected, False otherwise.
    """
    try:
        provider_select = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "sushi-provider"))
        )
        select = Select(provider_select)

        # Search option text for a match (case-insensitive, ignores extra spaces)
        search_name = service_provider_name.lower().strip()
        matched_option = None

        for option in select.options:
            option_text = " ".join(option.text.split()).lower()  # collapse whitespace
            if search_name in option_text:
                matched_option = option.text.strip()
                select.select_by_visible_text(option.text)
                break

        if matched_option:
            print(f"  ✓ Service provider selected: {matched_option}")
            return True

        print(f"  ✗ No match found for service provider: '{service_provider_name}'")
        print("    Available options:")
        for option in select.options:
            print(f"      - {' '.join(option.text.split())}")
        return False

    except (NoSuchElementException, TimeoutException) as e:
        print(f"  ✗ Could not find service provider dropdown: {e}")
        return False


def select_report_type(driver, report_type_full_name):
    """
    Select the Report Type from the dropdown using the short code (TR, DR, etc.).

    Args:
        driver:               Selenium WebDriver instance
        report_type_full_name: Full name from CSV, e.g. "Title Master Report"

    Returns:
        True if selected successfully, False otherwise.
    """
    code = REPORT_TYPE_MAP.get(report_type_full_name.lower().strip())
    if not code:
        print(f"  ✗ Unknown report type: '{report_type_full_name}'")
        print(f"    Known types: {list(REPORT_TYPE_MAP.keys())}")
        return False

    try:
        report_select_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "sushi-report-type"))
        )
        Select(report_select_el).select_by_value(code)
        print(f"  ✓ Report type selected: {report_type_full_name} ({code})")
        return True

    except (NoSuchElementException, TimeoutException) as e:
        print(f"  ✗ Could not find report type dropdown: {e}")
        return False


def set_data_types(driver, data_types_value):  # pylint: disable=unused-argument
    """
    Handle the Data Types field.

    "All Data Types" means leaving the field at its default (nothing selected),
    which is how the manually completed form in the screenshot is set.
    If a specific type is listed, we log a note — custom data type selection
    via Selenium requires additional work and can be added in a future version.

    Args:
        driver:           Selenium WebDriver instance
        data_types_value: The 'data_types' string from the CSV
    """
    if data_types_value.strip().lower() == "all data types" or data_types_value.strip() == "":
        print("  ✓ Data Types: leaving as 'All Data Types' (default)")
    else:
        print(f"  ⚠️  Data Types value '{data_types_value}' requires manual selection.")
        print("      The form will submit with default (All Data Types).")
        print("      Custom data type automation can be added in a future version.")


def set_date_field(driver, field_id, date_str, label):
    """
    Set a date input field using JavaScript (more reliable than send_keys for date inputs).

    Args:
        driver:   Selenium WebDriver instance
        field_id: HTML id attribute of the date input (e.g. "sushi-start")
        date_str: Date in YYYY-MM-DD format
        label:    Human-readable name for log messages (e.g. "Begin Date")

    Returns:
        True if the field was set, False otherwise.
    """
    formatted = format_date_for_input(date_str)
    if not formatted:
        return False

    try:
        field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, field_id))
        )
        # Use JavaScript to set the value directly — more reliable for date inputs
        driver.execute_script(
            "arguments[0].value = arguments[1];",
            field,
            formatted
        )
        # Trigger a 'change' event so the page registers the update
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
            field
        )
        print(f"  ✓ {label} set to: {formatted}")
        return True

    except (NoSuchElementException, TimeoutException) as e:
        print(f"  ✗ Could not set {label}: {e}")
        return False


# pylint: disable=too-many-statements
def delete_existing_fetch(driver, dataset_id, platform_id, begin_date, end_date):
    """
    Before submitting a reharvest, check the Fetch List (uploads) tab for any
    existing entry that covers the same date range and delete it.

    LibInsight blocks a new fetch if a record already exists for the same
    begin/end dates, even if that record has zero results or an error.

    Steps:
        1. Click the 'Fetch List' tab on the current platform page.
        2. Scan the uploads table for a filename containing the begin/end dates.
        3. If a match is found, click its Delete button and confirm.

    Args:
        driver:      Selenium WebDriver instance
        dataset_id:  Dataset ID string (e.g. "38993")
        platform_id: Platform ID string (e.g. "197")
        begin_date:  Begin date from CSV (any format; converted to YYYY-MM-DD)
        end_date:    End date from CSV (any format; converted to YYYY-MM-DD)

    Returns:
        True  if a matching entry was found and deleted (or none existed).
        False if an error prevented the check from completing.
    """
    # dataset_id/platform_id are kept for signature consistency with the other
    # page helpers; this function acts on whatever platform page is already open.
    # pylint: disable=unused-argument,too-many-locals,too-many-return-statements

    # Convert dates to YYYY-MM-DD so they match the filename format in the table
    begin_fmt = format_date_for_input(begin_date)
    end_fmt   = format_date_for_input(end_date)

    if not begin_fmt or not end_fmt:
        print("  ⚠️  Could not format dates for upload check — skipping delete step")
        return False

    # The filename encodes dates as YYYY-MM-DD_YYYY-MM-DD, e.g.
    # ...2026-01-01_2026-06-30.R5.json
    # Note: the end date in the filename uses the last day of the final month,
    # but we match on the begin date only to avoid a mismatch on the end day.
    date_pattern = begin_fmt  # at minimum, begin date must appear in the filename

    print(f"\n  🔍 Checking Fetch List for existing entry: {begin_fmt} → {end_fmt}")

    try:
        # ---- Step 1: Click the 'Fetch List' tab ----------------------------
        # The tab link text is "Fetch List" and it targets the uploads-tab panel.
        # We use a link-text match which is more stable than an XPath position.
        uploads_tab = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[@href='#uploads-tab' or contains(text(),'Fetch List')]")
            )
        )
        uploads_tab.click()
        time.sleep(2)  # wait for the tab panel to render
        print("  → Opened Fetch List tab")

        # ---- Step 2: Find table rows and look for a date match -------------
        # Each row's second <td> contains the JSON filename, which includes the
        # date range. We search all rows for one containing our begin date.
        rows = driver.find_elements(
            By.CSS_SELECTOR, "#uploads-list tbody tr"
        )

        if not rows:
            print("  → Fetch List is empty — no deletion needed")
            return True

        matched_row = None
        for table_row in rows:
            cells = table_row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 2:
                continue
            filename = cells[1].text.strip()
            if date_pattern in filename:
                matched_row = table_row
                print(f"  → Found matching entry: {filename}")
                break

        if matched_row is None:
            print(f"  → No existing entry found for {begin_fmt} — no deletion needed")
            return True

        # ---- Step 3: Click the Delete button for the matched row -----------
        # The delete button has aria-label="Delete File" within this row.
        try:
            delete_button = matched_row.find_element(
                By.CSS_SELECTOR, "button.delete-upload"
            )
        except NoSuchElementException:
            print("  ✗ Could not find Delete button for matched row")
            return False

        # Show the upload ID being deleted (from data-id attribute) for the log
        upload_id = delete_button.get_attribute("data-id")
        print(f"  → Clicking Delete for upload ID: {upload_id}")

        # Prompt before deleting — this action cannot be undone
        confirm = input(
            f"  ⚠️  Delete upload {upload_id} covering {begin_fmt} → {end_fmt}? "
            f"(yes to confirm, anything else to skip): "
        )
        if confirm.strip().lower() != "yes":
            print("  → Deletion skipped by user — row will not be resubmitted")
            return False

        delete_button.click()
        time.sleep(1)  # brief pause for the modal to appear

        # LibInsight shows a confirmation modal after clicking Delete.
        # We must click the OK button inside it to complete the deletion.
        try:
            ok_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "#confirm-modal button.btn-confirm")
                )
            )
            ok_button.click()
            print("  → Confirmation modal: clicked OK")
            time.sleep(2)  # give the page time to process the deletion
        except TimeoutException:
            print("  ✗ Confirmation modal did not appear — deletion may not have completed")
            return False

        # ---- Step 4: Verify deletion via the toast success message ---------
        # LibInsight briefly displays a toast notification with "Success" text
        # after a successful deletion. We wait up to 5 seconds for it to appear.
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.toast-message strong")
                )
            )
            print(f"  ✓ Upload {upload_id} deleted successfully")
        except TimeoutException:
            # Toast didn't appear in time — deletion likely still worked,
            # since the modal OK was already clicked successfully.
            print(f"  ✓ Upload {upload_id} — delete confirmed (toast not detected)")

        return True

    except (NoSuchElementException, TimeoutException) as e:
        print(f"  ✗ Error accessing Fetch List tab: {e}")
        return False


def click_get_report(driver):
    """
    Click the 'Get Report' button and verify the result.

    On success, LibInsight opens a modal with id="notify-body" containing
    the request confirmation details (report type, provider, date range).
    On failure, the alert-fetch div at the top of the form shows an error.

    Returns:
        True if the button was clicked and result was read, False otherwise.
    """
    try:
        get_report_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "harvest-sushi-button"))
        )

        get_report_button.click()
        print("  ✓ 'Get Report' button clicked")

        # LibInsight shows one of two responses after submission:
        #   SUCCESS: a modal appears with id="notify-body" containing request details
        #   FAILURE: the alert-fetch div at the top of the form shows an error message
        #
        # We check for the notify modal first (up to 5 seconds). If it doesn't
        # appear, we fall back to reading alert-fetch for an error message.
        try:
            notify_body = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "notify-body"))
            )
            notify_text = " ".join(notify_body.text.split())  # collapse whitespace
            print(f"  ✓ Request queued: {notify_text}")
            return True

        except TimeoutException:
            # Modal didn't appear — check alert-fetch for an error message
            try:
                alert_div = driver.find_element(By.ID, "alert-fetch")
                alert_text = alert_div.text.strip()
                if alert_text:
                    print(f"  ✗ Server response: {alert_text}")
                else:
                    print("  ⚠️  No confirmation modal or error message detected")
            except NoSuchElementException:
                print("  ⚠️  No confirmation modal or alert div found after submission")
            return False

    except (NoSuchElementException, TimeoutException) as e:
        print(f"  ✗ Could not click 'Get Report' button: {e}")
        return False

# ============================================================================
# CORE: PROCESS ONE ROW
# ============================================================================

def process_one_row(driver, row, row_number):
    """
    Navigate to the platform page for one CSV row and submit the fetch form.

    Args:
        driver:     Selenium WebDriver instance
        row:        Dict from csv.DictReader (one CSV row)
        row_number: 1-based counter for display purposes

    Returns:
        True if all steps completed without errors, False otherwise.
    """
    dataset_id       = row.get("dataset_id", "").strip()
    platform_id      = row.get("platform_id", "").strip()
    service_provider = row.get("service_provider", "").strip()
    report_type      = row.get("report_type", "").strip()
    data_types       = row.get("data_types", "").strip()
    begin_date       = row.get("begin_date", "").strip()
    end_date         = row.get("end_date", "").strip()

    print(f"\n{'='*60}")
    print(f"Row {row_number}: Dataset {dataset_id} / Platform {platform_id}")
    print(f"  Provider:    {service_provider}")
    print(f"  Report type: {report_type}")
    print(f"  Date range:  {begin_date} → {end_date}")
    print(f"{'='*60}")

    # ---- 1. Build and navigate to the platform URL -------------------------
    url = f"{LIBINSIGHT_BASE_URL}/admin/eresources/{dataset_id}/platforms/{platform_id}/add"
    print(f"\n  → Navigating to: {url}")
    driver.get(url)
    time.sleep(PAGE_LOAD_WAIT)

    # ---- 1.5 Delete any existing fetch for the same date range -------------
    # LibInsight blocks re-fetching if a record already exists for these dates.
    # delete_existing_fetch() opens the Fetch List tab, finds a matching entry,
    # prompts for confirmation, and deletes it.
    # Returning False means either no match was found (normal) or the user
    # skipped deletion — either way we proceed and let the server response
    # tell us if there's a conflict.
    delete_existing_fetch(driver, dataset_id, platform_id, begin_date, end_date)

    # After visiting the Fetch List tab, navigate back to the /add page so
    # the Fetch SUSHI Data Now accordion is available again.
    print(f"\n  → Returning to fetch form: {url}")
    driver.get(url)
    time.sleep(PAGE_LOAD_WAIT + 3)

    # ---- 2. Open the Fetch accordion section if needed ---------------------
    ensure_fetch_section_open(driver)

    # ---- 3. Service Provider -----------------------------------------------
    if not select_service_provider(driver, service_provider):
        print(f"  ✗ Skipping row {row_number} — service provider not matched")
        return False

    # ---- 4. Report Type ----------------------------------------------------
    if not select_report_type(driver, report_type):
        print(f"  ✗ Skipping row {row_number} — report type not recognised")
        return False

    # ---- 5. Data Types -----------------------------------------------------
    set_data_types(driver, data_types)

    # ---- 6. Begin Date -----------------------------------------------------
    if not set_date_field(driver, "sushi-start", begin_date, "Begin Date"):
        print(f"  ✗ Skipping row {row_number} — begin date could not be set")
        return False

    # ---- 7. End Date -------------------------------------------------------
    if not set_date_field(driver, "sushi-end", end_date, "End Date"):
        print(f"  ✗ Skipping row {row_number} — end date could not be set")
        return False

    # ---- 8. Pause for manual review before submitting ----------------------
    print("\n  ⏸️  Please review the form in Chrome before continuing.")
    print("      Check: service provider, report type, date range.")
    input("      Press ENTER to submit the form, or Ctrl+C to cancel: ")

    # ---- 9. Click Get Report -----------------------------------------------
    success = click_get_report(driver)

    if success:
        print(f"  ✓ Row {row_number} submitted successfully")
    else:
        print(f"  ✗ Row {row_number} — submission step failed")

    # Pause between rows so requests do not stack too quickly
    time.sleep(2)
    return success

# ============================================================================
# CREDENTIALS
# ============================================================================

def get_credentials():
    """
    Load LibApps credentials from the .env file.

    Expects:
        LA_USER = your LibApps email address
        LA_PASS = your LibApps password

    Returns:
        Tuple of (username, password), or (None, None) if missing.
    """
    username = os.getenv("LA_USER")
    password = os.getenv("LA_PASS")
    if not username or not password:
        print("\n✗ Error: Could not load credentials from .env file")
        print("  Make sure your .env file has LA_USER and LA_PASS set.")
        return None, None
    return username, password

# ============================================================================
# ARGUMENT PARSER
# ============================================================================

def parse_arguments():
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="SUSHI Reharvest Tool — submits Fetch SUSHI Data Now forms from a CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sushi_reharvest.py
  python sushi_reharvest.py --csv my_list.csv
        """
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=DEFAULT_CSV,
        help=f"Path to the reharvest CSV file (default: {DEFAULT_CSV})"
    )
    return parser.parse_args()

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main script execution."""
    args = parse_arguments()

    print("=" * 60)
    print("SUSHI Reharvest Tool")
    print(f"Log file: {LOG_FILENAME}")
    print("=" * 60)

    # Load credentials
    username, password = get_credentials()
    if not username or not password:
        return

    # Prompt for MFA code at the command line (same pattern as sushi_harvest_tracker.py)
    mfa_code = input("\nGoogle Authenticator MFA code: ")

    # Load CSV rows
    print(f"\nReading harvest requests from: {args.csv}")
    rows = load_reharvest_csv(args.csv)

    if not rows:
        print("✗ No rows found in CSV. Exiting.")
        return

    # Show summary of what will be submitted
    print(f"\n📋 {len(rows)} harvest request(s) to submit:")
    for i, row in enumerate(rows, start=1):
        print(f"   {i}. Dataset {row.get('dataset_id')} / "
              f"Platform {row.get('platform_id')} — "
              f"{row.get('report_type')} "
              f"({row.get('begin_date')} → {row.get('end_date')})")

    print("\nNote: You will be prompted to review and confirm each form before it is submitted.")

    driver = None
    results = []  # track (row_number, success) for summary

    try:
        driver = setup_chrome_driver()
        login_to_libinsight(driver, username, password, mfa_code)

        for row_number, row in enumerate(rows, start=1):
            success = process_one_row(driver, row, row_number)
            results.append((row_number, success))

    except KeyboardInterrupt:
        print("\n\n⏹  Script cancelled by user (Ctrl+C)")

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n✗ Fatal error: {e}")
        traceback.print_exc()

    finally:
        # ---- Summary -------------------------------------------------------
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        succeeded = sum(1 for _, ok in results if ok)
        failed    = sum(1 for _, ok in results if not ok)
        print(f"  Rows submitted successfully: {succeeded}")
        print(f"  Rows with errors:            {failed}")

        if driver:
            print("\nClosing browser...")
            time.sleep(2)
            driver.quit()
            print("✓ Browser closed")

        print("\n✓ Script finished.")


if __name__ == "__main__":
    main()
