"""
LibInsight SUSHI Harvest Status Tracker
This script logs into LibInsight, extracts SUSHI harvest status data,
and optionally re-enables disabled harvests.
"""

import time
import os
import csv
from dotenv import load_dotenv
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from getpass import getpass

# ============================================================================
# CONFIGURATION SECTION
# ============================================================================

load_dotenv()

# Set to True to automatically re-enable disabled harvests
AUTO_ENABLE_DISABLED_HARVESTS = False  # Change to True to enable auto-fixing

# LibInsight base URL
LIBINSIGHT_BASE_URL = "https://acaweb.libinsight.com"
LIBAPPS_BASE_URL = "https://acaweb.libapps.com"

# Dataset and Platform combinations to check
# Format: (dataset_id, platform_id, dataset_name, library_name)
DATASETS_TO_CHECK = [
    (38772, 151, "aca JSTOR", "Alice Lloyd College"),
    (38772, 152, "aca JSTOR", "Berea College"),
    (38993, 196, "aca Oxford Grove", "Alice Lloyd College")
]

# Output CSV filename
OUTPUT_CSV = "SUSHI_harvest_status_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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
            raise Exception("Login verification failed")
        
        print("✓ Login successful!")

        # DEBUGGING: Pause to let you check the browser
        # input("\n⏸️  Press ENTER to continue (check the browser window first)...")
        
    except TimeoutException:
        print("✗ Error: Login page elements not found. Check the page structure.")
        raise
    except Exception as e:
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
        sushi_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Schedule Future SUSHI Harvesting')]")
        
        # Check if section is collapsed (button itself has "collapsed" class)
        button_classes = sushi_button.get_attribute("class")
        if "collapsed" in button_classes:
            sushi_button.click()
            time.sleep(2)  # Give the section time to expand
            print("  → Expanded SUSHI section")
            
    except NoSuchElementException:
        # Section might already be expanded
        pass


def extract_sushi_table_data(driver, dataset_name, library_name):
    """
    Extract all rows from the SUSHI harvesting table.
    
    Args:
        driver: Selenium WebDriver instance
        dataset_name: Name of the dataset (e.g., "aca JSTOR")
        library_name: Name of the library (e.g., "Alice Lloyd College")
        
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
                # Extract data from each column
                cells = row.find_elements(By.TAG_NAME, "td")
                
                # DEBUGGING: Print what we found
                # print(f"\n  DEBUG: Found {len(cells)} cells in this row")
                # for i, cell in enumerate(cells):
                  #   cell_text = cell.text.strip()
                    # cell_html = cell.get_attribute('innerHTML')[:100]  # First 100 chars
                    # print(f"    Cell {i}: text='{cell_text}' | html='{cell_html}'")
                # END DEBUGGING
                
                if len(cells) < 7:  # Need at least 7 columns
                    continue
                
                if len(cells) < 7:  # Need at least 7 columns
                    continue
                
                # Parse each column (get text -- doesn't work for LibInsight but keep for reference)
                # schedule_id = cells[0].text.strip()
                # report_type = cells[1].text.strip()
                # vendor = cells[2].text.strip()
                # frequency = cells[3].text.strip()
                # recurring_until = cells[4].text.strip()
                # last_fetch = cells[5].text.strip()
                # enabled = cells[6].text.strip()

                # Parse each column (get html element because LibInsight is not loading table early enough)
                schedule_id = cells[0].get_attribute('textContent').strip()
                report_type = cells[1].get_attribute('textContent').strip()
                vendor = cells[2].get_attribute('textContent').strip()
                frequency = cells[3].get_attribute('textContent').strip()
                recurring_until = cells[4].get_attribute('textContent').strip()
                last_fetch = cells[5].get_attribute('textContent').strip()
                enabled = cells[6].get_attribute('textContent').strip()
                
                # Create row dictionary
                row_data = {
                    "library": library_name,
                    "dataset_name": dataset_name,
                    "schedule_id": schedule_id,
                    "report_type": report_type,
                    "vendor": vendor,
                    "frequency": frequency,
                    "recurring_until": recurring_until,
                    "last_fetch": last_fetch,
                    "enabled": enabled,
                    "has_error": "error" in last_fetch.lower()
                }
                
                rows_data.append(row_data)
                
                # Print status
                status_symbol = "✗" if row_data["has_error"] else "✓"
                enabled_symbol = "✓" if enabled.lower() == "yes" else "✗"
                print(f"    {status_symbol} Schedule {schedule_id}: {report_type} - Enabled: {enabled_symbol}")
                
                if row_data["has_error"]:
                    print(f"      Error: {last_fetch[:100]}...")
                    
            except Exception as e:
                print(f"    ✗ Error parsing row: {e}")
                continue
                
    except TimeoutException:
        print("  ✗ SUSHI table not found on this page")
    except Exception as e:
        print(f"  ✗ Error extracting table data: {e}")
    
    return rows_data


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
        
        # Find the edit button (pencil icon) for this schedule
        # The button is in the Actions column and has an onclick attribute
        edit_button = driver.find_element(
            By.XPATH, 
            f"//tr[td[text()='{schedule_id}']]//a[@title='Edit']"
        )
        
        # Click the edit button to open the modal
        edit_button.click()
        time.sleep(2)
        
        # Wait for modal to open
        modal = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.modal-content"))
        )
        
        # Find and click the "Enabled" radio button
        enabled_radio = modal.find_element(By.XPATH, "//input[@type='radio' and @value='1']")
        
        # Check if it's already enabled
        if enabled_radio.is_selected():
            print(f"    ✓ Schedule {schedule_id} is already enabled")
            # Close modal
            close_button = modal.find_element(By.XPATH, "//button[text()='Close']")
            close_button.click()
            time.sleep(1)
            return True
        
        # Click to enable
        enabled_radio.click()
        print(f"    ✓ Clicked 'Enabled' radio button")
        time.sleep(1)
        
        # Click Save button
        save_button = modal.find_element(By.XPATH, "//button[text()='Save']")
        save_button.click()
        time.sleep(2)
        
        print(f"    ✓ Schedule {schedule_id} has been enabled!")
        return True
        
    except Exception as e:
        print(f"    ✗ Error enabling schedule {schedule_id}: {e}")
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
        
    except Exception as e:
        print(f"✗ Error saving CSV: {e}")


# ============================================================================
# MAIN SCRIPT
# ============================================================================

def main():
    """Main script execution."""
    
    print("=" * 70)
    print("LibInsight SUSHI Harvest Status Tracker")
    print("=" * 70)
    
    # Get credentials from user
    # print("\nPlease enter your LibInsight credentials:")
    # username = input("Username: ")
    # password = getpass("Password (hidden): ")
    username = os.getenv("LA_USER")
    password = os.getenv("LA_PASS")
    if not username or not password:
        print("\n✗ Error: Could not load credentials from .env file")
        print("Please make sure you have a .env file with LA_USER and LA_PASS")
        return
    # Enter Google Authenticator MFA code in CLI
    mfa_code = input("Google Authenticator MFA code: ")
    
    # Initialize Chrome driver
    driver = None
    all_harvest_data = []
    
    try:
        driver = setup_chrome_driver()
        
        # Log in
        login_to_libinsight(driver, username, password, mfa_code)
        
        # Process each dataset/platform combination
        print("\n" + "=" * 70)
        print("Extracting SUSHI Harvest Data")
        print("=" * 70)
        
        for dataset_id, platform_id, dataset_name, library_name in DATASETS_TO_CHECK:
            print(f"\n📊 Processing: {library_name} - {dataset_name}")
            print(f"   Dataset ID: {dataset_id}, Platform ID: {platform_id}")
            
            # Navigate to the platform page
            navigate_to_platform_page(driver, dataset_id, platform_id)
            
            # Expand SUSHI section if needed
            expand_sushi_section(driver)
            
            # Extract table data
            rows = extract_sushi_table_data(driver, dataset_name, library_name)
            
            # If auto-enable is turned on, enable any disabled harvests
            if AUTO_ENABLE_DISABLED_HARVESTS:
                for row in rows:
                    if row["enabled"].lower() != "yes":
                        print(f"\n    ⚙️  Schedule {row['schedule_id']} is disabled. Attempting to enable...")
                        success = enable_disabled_harvest(driver, row["schedule_id"])
                        if success:
                            row["enabled"] = "Yes (Auto-enabled)"
            
            # Add to overall data
            all_harvest_data.extend(rows)
            
            # Small pause between datasets
            time.sleep(1)
        
        # Save all data to CSV
        print("\n" + "=" * 70)
        save_to_csv(all_harvest_data, OUTPUT_CSV)
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total schedules processed: {len(all_harvest_data)}")
        
        error_count = sum(1 for row in all_harvest_data if row["has_error"])
        print(f"Schedules with errors: {error_count}")
        
        disabled_count = sum(1 for row in all_harvest_data if row["enabled"].lower() != "yes")
        print(f"Disabled schedules: {disabled_count}")
        
        if AUTO_ENABLE_DISABLED_HARVESTS and disabled_count > 0:
            print(f"\n✓ Auto-enable was ON - attempted to enable all disabled schedules")
        elif disabled_count > 0:
            print(f"\n⚠️  Auto-enable is OFF - {disabled_count} schedules remain disabled")
            print("   To enable auto-fix, set AUTO_ENABLE_DISABLED_HARVESTS = True")
        
        print("\n✓ Script completed successfully!")
        
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
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
