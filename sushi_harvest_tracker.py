"""
LibInsight SUSHI Harvest Status Tracker
This script logs into LibInsight, extracts SUSHI harvest status data,
and optionally re-enables disabled harvests.
"""

import argparse
import csv
import os
import sys
import time

# from getpass import getpass # restore if using in main()
import traceback
from datetime import datetime

import requests
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
from selenium.webdriver.support.ui import WebDriverWait

from springshare_auth import SpringshareAuth

# ============================================================================
# CONFIGURATION SECTION
# ============================================================================

# Timeout (seconds) applied to outbound HTTP requests.
REQUEST_TIMEOUT = 30


# Create logs directory if it doesn't exist
def setup_logging():
    """
    Create the logs directory and mirror stdout/stderr to a timestamped log file.

    Returns:
        The path to the log file that was created.
    """
    os.makedirs("logs", exist_ok=True)
    log_filename = datetime.now().strftime("logs/sushi_harvest_%Y%m%d_%H%M%S.log")

    # Echo output to terminal and redirect stdout and stderr to the log file
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

    # Send output to both terminal AND log file
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

# Set to True to automatically re-enable disabled harvests
# Edit in script or override with CLI flag --auto-enable
AUTO_ENABLE_DISABLED_HARVESTS = False  # Change to True to enable auto-fixing

# LibInsight base URL
LIBINSIGHT_BASE_URL = "https://acaweb.libinsight.com"
LIBAPPS_BASE_URL = "https://acaweb.libapps.com"

# Dataset and Platform combinations to check
# Format: (dataset_id, platform_id, dataset_name, library_name)
DATASETS_TO_CHECK = [
    (37166, 298, "aca Evans Newsbank", "Bethany College"),
    (37166, 304, "aca Evans Newsbank", "Davis & Elkins College"),
    (38993, 219, "aca Oxford Grove", "Tennessee Wesleyan University")
]

# Dataset IDs for auto-discovery mode (used with --auto-discover flag)
# Add or remove dataset IDs as needed [38772, 40156, 37166, 39017, 38993]
FIND_PLATFORMS = [38772, 40156, 37166, 39017, 38993]

# Output CSV filename
OUTPUT_CSV = "SUSHI_harvest_status_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_platforms_for_dataset(dataset_id, access_token, skip_list=None):
    """
    Fetch all platforms for a given dataset from the Platforms API.

    Args:
        dataset_id: The dataset ID
        access_token: OAuth access token
        skip_list: Set of platform IDs to skip (optional)

    Returns:
        List of tuples: (dataset_id, platform_id, dataset_name, library_name)
    """
    if skip_list is None:
        skip_list = set()

    url = f"https://acaweb.libinsight.com/v1.0/e-resources/{dataset_id}/platforms"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        # Get dataset name
        dataset_name = f"Dataset {dataset_id}"

        # Extract platforms
        platforms = data.get('payload', {}).get('platforms', [])

        # Build tuples, skipping any in the skip list
        platform_tuples = []
        for platform in platforms:
            platform_id = platform.get('id')
            library_name = platform.get('name', 'Unknown Library')

            # Skip if in skip list
            if platform_id in skip_list:
                print(f"  → Skipping platform {platform_id} ({library_name}) - in skip list")
                continue

            platform_tuples.append((dataset_id, platform_id, dataset_name, library_name))

        return platform_tuples

    except (requests.RequestException, ValueError) as e:
        print(f"  ✗ Error fetching platforms for dataset {dataset_id}: {e}")
        return []


def load_skip_list(filename):
    """
    Load platform IDs to skip from a text file.

    Args:
        filename: Path to text file with one platform ID per line

    Returns:
        Set of platform IDs (as integers)
    """
    skip_list = set()

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):  # Skip empty lines and comments
                    try:
                        skip_list.add(int(line))
                    except ValueError:
                        print(f"  ⚠️  Warning: Skipping invalid platform ID in skip list: {line}")

        print(f"✓ Loaded {len(skip_list)} platform IDs from skip list")
        return skip_list

    except FileNotFoundError:
        print(f"✗ Error: Skip list file not found: {filename}")
        sys.exit(1)
    except OSError as e:
        print(f"✗ Error reading skip list: {e}")
        sys.exit(1)


def setup_chrome_driver():
    """
    Set up Chrome WebDriver with options.
    Returns: configured Chrome WebDriver instance
    """
    print("Setting up Chrome driver...")

    # Chrome options for better stability
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    # Create and return the driver
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def login_to_libinsight(driver, username, password, mfa_code):
    """
    Log into LibInsight using username, password, and MFA code.

    Args:
        driver: Selenium WebDriver instance
        username: LibApps username
        password: LibApps password
        mfa_code: Google Authenticator MFA code
    """
    print("\nLogging into LibInsight...")

    # Navigate to login page
    driver.get(f"{LIBAPPS_BASE_URL}/libapps/login.php?site_id=25079&target=admin/welcome")

    # Wait for and fill in username
    try:
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-email"))
        )
        username_field.send_keys(username)
        print("✓ Username entered")

        # Fill in password
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-password"))
        )
        password_field.send_keys(password)
        print("✓ Password entered")

        # Click "Sign In" button
        signin_button = driver.find_element(By.ID, "s-libapps-login-button")
        signin_button.click()
        time.sleep(2)

        # Fill in MFA code
        mfa_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "s-libapps-code"))
        )
        mfa_field.send_keys(mfa_code)
        print("✓ MFA code entered")

        # Click "Verify" button
        verify_button = driver.find_element(By.ID, "s-libapps-mfa-button")
        verify_button.click()
        time.sleep(3)

        # Verify login was successful by checking the current URL
        current_url = driver.current_url
        print(f"  → Current URL after login: {current_url}")

        # If we're still on the login page, something went wrong
        if "login" in current_url.lower():
            print("✗ Login failed - still on login page")
            print("  Possible reasons:")
            print("  - MFA code expired (they only last 30 seconds)")
            print("  - Wrong username or password")
            print("  - Website structure changed")
            raise RuntimeError("Login verification failed")

        print("✓ Login successful!")

        # DEBUGGING: Pause to let you check the browser
        # input("\n⏸️  Press ENTER to continue (check the browser window first)...")

    except TimeoutException:
        print("✗ Error: Login page elements not found. Check the page structure.")
        raise
    except WebDriverException as e:
        print(f"✗ Error during login: {e}")
        raise


def navigate_to_platform_page(driver, dataset_id, platform_id):
    """
    Navigate to the specific dataset/platform "Add Data" page.

    Args:
        driver: Selenium WebDriver instance
        dataset_id: LibInsight dataset ID
        platform_id: LibInsight platform ID
    """
    url = f"{LIBINSIGHT_BASE_URL}/admin/eresources/{dataset_id}/platforms/{platform_id}/add"
    driver.get(url)
    time.sleep(2)


def expand_sushi_section(driver):
    """
    Click to expand the "Schedule Future SUSHI Harvesting" section if collapsed.

    Args:
        driver: Selenium WebDriver instance
    """
    try:
        # Look for the "Schedule Future SUSHI Harvesting" button
        sushi_button = driver.find_element(
            By.XPATH,
            "//button[contains(text(), 'Schedule Future SUSHI Harvesting')]"
        )

        # Check if section is collapsed (button itself has "collapsed" class)
        button_classes = sushi_button.get_attribute("class")
        if "collapsed" in button_classes:
            sushi_button.click()
            time.sleep(2)  # Give the section time to expand
            print("  → Expanded SUSHI section")

    except NoSuchElementException:
        # Section might already be expanded
        pass

    # IMPORTANT: Wait for DataTable to fully initialize after expanding
    print("  → Waiting for DataTable to initialize...")
    time.sleep(3)  # DataTables need extra time to render


def _parse_sushi_row(row, dataset_name, library_name, platform_id):
    """
    Parse a single SUSHI table row into a data dictionary.

    Returns:
        A row dictionary, or None if the row does not have enough columns.
    """
    # Extract data from each column
    cells = row.find_elements(By.TAG_NAME, "td")

    if len(cells) < 8:  # Need at least 8 columns
        return None

    # Parse each column (get html element because LibInsight is not loading
    # the table early enough for .text to be populated)
    schedule_id = cells[0].get_attribute('textContent').strip()
    report_type = cells[1].get_attribute('textContent').strip()
    vendor = cells[2].get_attribute('textContent').strip()
    frequency = cells[3].get_attribute('textContent').strip()
    recurring_until = cells[4].get_attribute('textContent').strip()
    last_fetch = cells[5].get_attribute('textContent').strip()
    enabled = cells[6].get_attribute('textContent').strip()

    return {
        "library": library_name,
        "dataset_name": dataset_name,
        "platform_id": platform_id,
        "schedule_id": schedule_id,
        "report_type": report_type,
        "vendor": vendor,
        "frequency": frequency,
        "recurring_until": recurring_until,
        "last_fetch": last_fetch,
        "enabled": enabled,
        "has_error": "error" in last_fetch.lower()
    }


def extract_sushi_table_data(driver, dataset_name, library_name, platform_id):
    """
    Extract all rows from the SUSHI harvesting table.

    Args:
        driver: Selenium WebDriver instance
        dataset_name: Name of the dataset (e.g., "aca JSTOR")
        library_name: Name of the library (e.g., "Alice Lloyd College")
        platform_id: Platform identifier (e.g., 151)

    Returns:
        List of dictionaries containing row data
    """
    rows_data = []

    try:
        # Wait for table to load AND have data rows
        # This waits for at least one row to appear in the table body
        rows = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#schedule-table tbody tr"))
        )

        print(f"  → Found {len(rows)} SUSHI schedules")

        for row in rows:
            try:
                row_data = _parse_sushi_row(row, dataset_name, library_name, platform_id)
                if row_data is None:
                    continue

                rows_data.append(row_data)

                # Print status
                status_symbol = "✗" if row_data["has_error"] else "✓"
                enabled_symbol = "✓" if row_data["enabled"].lower() == "yes" else "✗"
                print(
                    f"    {status_symbol} Schedule {row_data['schedule_id']}: "
                    f"{row_data['report_type']} - Enabled: {enabled_symbol}"
                )

                if row_data["has_error"]:
                    print(f"      Error: {row_data['last_fetch'][:100]}...")

            except WebDriverException as e:
                print(f"    ✗ Error parsing row: {e}")
                continue

    except TimeoutException:
        print("  ✗ SUSHI table not found on this page")
    except WebDriverException as e:
        print(f"  ✗ Error extracting table data: {e}")

    return rows_data


def _find_edit_button(driver, schedule_id):
    """Locate the edit button for a schedule row and scroll it into view."""
    # Wait for the schedule row in the DataTable
    print("    → Waiting for schedule row to appear in DataTable...")
    schedule_row = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            By.XPATH,
            f"//tr[td[text()='{schedule_id}']]"
        ))
    )

    # Find the edit button within that row
    edit_button = schedule_row.find_element(
        By.CSS_SELECTOR,
        "a.edit-schedule[data-id='" + str(schedule_id) + "']"
    )

    # Scroll the button into view and highlight it
    print("    → Found edit button, scrolling into view...")
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});"
        " arguments[0].style.border='3px solid red';",
        edit_button
    )
    time.sleep(1)  # Let the scroll complete
    return edit_button


def _click_with_fallbacks(driver, element):
    """Try several strategies to click an element. Returns True if one succeeds."""
    # Strategy A: Regular Selenium click
    try:
        print("    → Attempting regular click...")
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(element))
        element.click()
        print("    ✓ Regular click succeeded")
        return True
    except WebDriverException as e1:
        print(f"    → Regular click failed: {str(e1)[:50]}")

    # Strategy B: ActionChains click (simulates real mouse movement)
    try:
        print("    → Attempting ActionChains click...")
        ActionChains(driver).move_to_element(element).click().perform()
        print("    ✓ ActionChains click succeeded")
        return True
    except WebDriverException as e2:
        print(f"    → ActionChains click failed: {str(e2)[:50]}")

    # Strategy C: JavaScript click (most reliable for hidden/covered elements)
    try:
        print("    → Attempting JavaScript click...")
        driver.execute_script("arguments[0].click();", element)
        print("    ✓ JavaScript click succeeded")
        return True
    except WebDriverException as e3:
        print(f"    → JavaScript click failed: {str(e3)[:50]}")

    return False


def _wait_for_schedule_modal(driver):
    """Wait for the schedule modal to appear and finish animating."""
    # Wait for modal to start opening (look for the dark backdrop first)
    print("    → Waiting for modal backdrop to appear...")
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.modal-backdrop"))
        )
        print("    ✓ Modal backdrop appeared (dark screen visible)")
    except TimeoutException:
        print("    → No backdrop found, continuing anyway...")

    # Give the modal animation time to complete
    time.sleep(2)

    # Wait for modal to be in the DOM (not necessarily visible yet)
    print("    → Waiting for modal to be present in DOM...")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "scheduleModal"))
    )
    print("    ✓ Modal found in DOM")

    # Wait for it to finish animating (Bootstrap adds the "show" class)
    print("    → Waiting for modal to finish animating...")
    time.sleep(1)

    # Now look specifically for the modal body content to be present
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "scheduleModelBody"))
    )
    print("    ✓ Modal body loaded - modal is ready!")


def enable_disabled_harvest(driver, schedule_id):
    """
    Click the edit button for a schedule and enable it if disabled.

    Args:
        driver: Selenium WebDriver instance
        schedule_id: The ID of the schedule to enable

    Returns:
        True if successfully enabled, False otherwise
    """
    try:
        print(f"    → Attempting to enable schedule {schedule_id}...")

        edit_button = _find_edit_button(driver, schedule_id)

        if not _click_with_fallbacks(driver, edit_button):
            print("    ✗ All click methods failed")
            return False

        _wait_for_schedule_modal(driver)

        # Find the "Enabled" radio button within the modal
        print("    → Looking for Enabled radio button...")
        try:
            enabled_radio = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "#scheduleModal input[name='schedule-status'][value='1']"
                ))
            )
            print("    ✓ Found Enabled radio button")
        except TimeoutException:
            print("    ✗ Could not find Enabled radio button")
            # Take a screenshot for debugging
            driver.save_screenshot(f"debug_modal_schedule_{schedule_id}.png")
            print("    → Screenshot saved for debugging")
            return False

        # Check if it's already enabled
        if enabled_radio.is_selected():
            print(f"    ℹ️  Schedule {schedule_id} is already enabled")
            # Close modal by clicking Close button
            close_button = driver.find_element(
                By.CSS_SELECTOR, "#scheduleModal button[data-dismiss='modal']"
            )
            close_button.click()
            time.sleep(1)
            return True

        # Click to enable using JavaScript (radio buttons are often styled/hidden)
        print("    → Clicking 'Enabled' radio button using JavaScript...")
        driver.execute_script("arguments[0].checked = true; arguments[0].click();", enabled_radio)
        time.sleep(1)
        print("    ✓ Radio button clicked successfully")

        # Click Save button (also use JavaScript for reliability)
        print("    → Clicking Save button...")
        save_button = driver.find_element(By.CSS_SELECTOR, "#scheduleModal button#schedule-save")

        # Try regular click first, fall back to JavaScript
        try:
            save_button.click()
            print("    ✓ Save button clicked (regular click)")
        except WebDriverException:
            print("    → Regular click failed, using JavaScript...")
            driver.execute_script("arguments[0].click();", save_button)
            print("    ✓ Save button clicked (JavaScript)")

        # Wait for save to complete
        time.sleep(3)
        print(f"    ✓ Schedule {schedule_id} has been enabled!")
        return True

    except WebDriverException as e:
        print(f"    ✗ Error enabling schedule {schedule_id}: {e}")
        traceback.print_exc()
        return False


def save_to_csv(all_data, filename):
    """
    Save extracted data to CSV file.

    Args:
        all_data: List of dictionaries containing harvest data
        filename: Output CSV filename
    """
    print(f"\nSaving data to {filename}...")

    # Create the output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)

    # Build the full file path (combines "output" directory with filename)
    filepath = os.path.join("output", filename)

    # Define CSV columns
    fieldnames = [
        "library",
        "dataset_name",
        "platform_id",
        "schedule_id",
        "report_type",
        "vendor",
        "frequency",
        "recurring_until",
        "last_fetch",
        "enabled",
        "has_error"
    ]

    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_data)

        print(f"✓ Data saved successfully! ({len(all_data)} records)")

    except OSError as e:
        print(f"✗ Error saving CSV: {e}")


# ============================================================================
# MAIN SCRIPT
# ============================================================================

def parse_arguments():
    """Build the argument parser and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='LibInsight SUSHI Harvest Status Tracker',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--auto-discover',
        action='store_true',
        help='Automatically discover all platforms for datasets in FIND_PLATFORMS list'
    )

    parser.add_argument(
        '--skip-list',
        type=str,
        help='Path to text file containing platform IDs to skip (one per line)'
    )

    parser.add_argument(
        '--auto-enable',
        action='store_true',
        help='Automatically re-enable disabled platforms'
    )

    return parser.parse_args()


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


def discover_datasets(args):
    """
    Discover dataset/platform combinations from the API in auto-discover mode.

    Returns:
        List of (dataset_id, platform_id, dataset_name, library_name) tuples,
        or None if authentication failed.
    """
    print("\n" + "=" * 70)
    print("AUTO-DISCOVER MODE: Fetching platforms from API")
    print("=" * 70)

    # Get OAuth token for API calls
    print("\nAuthenticating with LibInsight API...")
    auth = SpringshareAuth()
    token_response = auth.get_token()

    if not token_response:
        print("✗ Failed to get API access token")
        return None

    access_token = token_response.get('access_token')
    print("✓ API token obtained")

    # Load skip list if provided
    skip_list = set()
    if args.skip_list:
        print(f"\nLoading skip list from: {args.skip_list}")
        skip_list = load_skip_list(args.skip_list)

    # Build platform list from API
    print(f"\nDiscovering platforms for {len(FIND_PLATFORMS)} datasets...")
    datasets_to_process = []

    for dataset_id in FIND_PLATFORMS:
        print(f"\n📊 Dataset {dataset_id}:")
        platforms = get_platforms_for_dataset(dataset_id, access_token, skip_list)
        print(f"  ✓ Found {len(platforms)} platforms")
        datasets_to_process.extend(platforms)

    print(f"\n✓ Total platforms to process: {len(datasets_to_process)}")
    return datasets_to_process


def process_datasets(driver, datasets_to_process, auto_enable):
    """
    Extract SUSHI harvest data for each dataset/platform, optionally enabling
    disabled harvests.

    Returns:
        List of harvest data dictionaries.
    """
    all_harvest_data = []

    for dataset_id, platform_id, dataset_name, library_name in datasets_to_process:
        print(f"\n📊 Processing: {library_name} - {dataset_name}")
        print(f"   Dataset ID: {dataset_id}, Platform ID: {platform_id}")

        # Navigate to the platform page
        navigate_to_platform_page(driver, dataset_id, platform_id)

        # Expand SUSHI section if needed
        expand_sushi_section(driver)

        # Extract table data
        rows = extract_sushi_table_data(driver, dataset_name, library_name, platform_id)

        # If auto-enable is turned on, enable any disabled harvests
        if auto_enable:
            for row in rows:
                if row["enabled"].lower() != "yes":
                    print(
                        f"\n    ⚙️  Schedule {row['schedule_id']} is disabled. "
                        "Attempting to enable..."
                    )
                    if enable_disabled_harvest(driver, row["schedule_id"]):
                        row["enabled"] = "Yes (Auto-enabled)"

        # Add to overall data
        all_harvest_data.extend(rows)

        # Small pause between datasets
        time.sleep(1)

    return all_harvest_data


def print_summary(all_harvest_data, auto_enable):
    """Print a summary of the harvest run."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total schedules processed: {len(all_harvest_data)}")

    error_count = sum(1 for row in all_harvest_data if row["has_error"])
    print(f"Schedules with errors: {error_count}")

    disabled_count = sum(1 for row in all_harvest_data if row["enabled"].lower() != "yes")
    print(f"Disabled schedules: {disabled_count}")

    if auto_enable and disabled_count > 0:
        print("\n✓ Auto-enable was ON - attempted to enable all disabled schedules")
    elif disabled_count > 0:
        print(f"\n⚠️  Auto-enable is OFF - {disabled_count} schedules remain disabled")
        print("   To enable auto-fix, set AUTO_ENABLE_DISABLED_HARVESTS = True")


def main():
    """Main script execution."""
    args = parse_arguments()

    print("=" * 70)
    print("LibInsight SUSHI Harvest Status Tracker")
    print(f"\n📄 Log file: {LOG_FILENAME}\n")
    print("=" * 70)

    # Show mode
    if args.auto_discover:
        print("\n🔍 Mode: AUTO-DISCOVER platforms from API")
        print(f"   Datasets to check: {FIND_PLATFORMS}")
    else:
        print("\n📋 Mode: MANUAL platform list")
        print(f"   Platforms to check: {len(DATASETS_TO_CHECK)}")

    if args.skip_list:
        print(f"   Skip list: {args.skip_list}")

    auto_enable = args.auto_enable
    if auto_enable:
        print("   Auto-enable lapsed platforms")
    else:
        print("\n Do not enable disabled harvests")

    # Get credentials from user
    # print("\nPlease enter your LibInsight credentials:")
    # username = input("Username: ")
    # password = getpass("Password (hidden): ")
    username, password = get_credentials()
    if not username or not password:
        return

    # Enter Google Authenticator MFA code in CLI
    mfa_code = input("Google Authenticator MFA code: ")

    # Handle auto-discover mode
    datasets_to_process = DATASETS_TO_CHECK  # Default to manual list

    if args.auto_discover:
        datasets_to_process = discover_datasets(args)
        if datasets_to_process is None:
            return
        if len(datasets_to_process) == 0:
            print("\n⚠️  No platforms found to process. Exiting.")
            return

    # Initialize Chrome driver
    driver = None

    try:
        driver = setup_chrome_driver()

        # Log in
        login_to_libinsight(driver, username, password, mfa_code)

        # Process each dataset/platform combination
        print("\n" + "=" * 70)
        print("Extracting SUSHI Harvest Data")
        print("=" * 70)

        all_harvest_data = process_datasets(driver, datasets_to_process, auto_enable)

        # Save all data to CSV
        print("\n" + "=" * 70)
        save_to_csv(all_harvest_data, OUTPUT_CSV)

        # Summary
        print_summary(all_harvest_data, auto_enable)

        print("\n✓ Script completed successfully!")

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n✗ Fatal error: {e}")
        traceback.print_exc()

    finally:
        # Clean up - close browser
        if driver:
            print("\nClosing browser...")
            time.sleep(2)
            driver.quit()
            print("✓ Browser closed")


if __name__ == "__main__":
    main()
