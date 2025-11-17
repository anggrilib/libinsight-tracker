# LibInsight SUSHI Harvest Tracker - Setup & Usage Guide

## Overview
This Python script uses Selenium to automate tracking SUSHI harvest errors in LibInsight. It can:
- Log into LibInsight with MFA
- Extract SUSHI harvest status data from multiple datasets
- Record error messages
- **Optionally** auto-enable disabled harvests
- Export everything to a CSV file

---

## Prerequisites

### 1. Python Installation
Make sure you have Python 3.7 or newer installed:
```bash
python --version
```

### 2. Install Required Packages
Open your terminal/command prompt and run:
```bash
pip install selenium
```

### 3. Install ChromeDriver
Selenium needs ChromeDriver to control Chrome. Two options:

**Option A: Automatic (Recommended)**
```bash
pip install webdriver-manager
```
Then modify the script (I can help with this if needed).

**Option B: Manual**
1. Check your Chrome version: Menu → Help → About Google Chrome
2. Download matching ChromeDriver from: https://chromedriver.chromium.org/downloads
3. Place it in a folder in your PATH, or note its location

---

## How to Run the Script

### Step 1: Download the Script
Save `sushi_harvest_tracker.py` to a folder on your computer.

### Step 2: Customize the Dataset List (Optional)
Open the script in a text editor and find the `DATASETS_TO_CHECK` section (around line 25):

```python
DATASETS_TO_CHECK = [
    (38772, 151, "aca JSTOR", "Alice Lloyd College"),
    (38772, 152, "aca JSTOR", "Berea College"),
    (38993, 196, "aca ASP", "Alice Lloyd College"),
    # Add more datasets here
]
```

**How to add a new dataset:**
1. Find a line that looks like: `(dataset_id, platform_id, "dataset_name", "library_name"),`
2. Copy that entire line
3. Paste it on a new line
4. Change the numbers and names to match your new dataset
5. Make sure to keep the comma at the end!

**Example - Adding a new college:**
```python
DATASETS_TO_CHECK = [
    (38772, 151, "aca JSTOR", "Alice Lloyd College"),
    (38772, 999, "aca JSTOR", "New College Name"),  # ← New line added
]
```

### Step 3: Enable/Disable Auto-Enable Feature
Find this line near the top (around line 20):

```python
AUTO_ENABLE_DISABLED_HARVESTS = False
```

**To turn ON auto-enabling:** Change `False` to `True`
**To turn OFF auto-enabling:** Change `True` to `False`

### Step 4: Run the Script
Open terminal/command prompt in the folder where you saved the script, then run:

```bash
python sushi_harvest_tracker.py
```

### Step 5: Enter Your Credentials
The script will prompt you for:
1. **Username**: Your LibInsight username
2. **Password**: Your LibInsight password (won't show on screen)
3. **MFA Code**: Current code from Google Authenticator

### Step 6: Watch It Work!
The script will:
- Open Chrome browser
- Log into LibInsight
- Visit each dataset/platform
- Extract the SUSHI table data
- Save everything to a CSV file

The browser will close automatically when finished.

---

## Understanding the Output

### CSV File
The script creates a file named: `SUSHI_harvest_status_YYYYMMDD_HHMMSS.csv`

**Columns:**
- `library` - Library name
- `dataset_name` - Dataset name (e.g., "aca JSTOR")
- `schedule_id` - Schedule ID number
- `report_type` - Type of report (e.g., "Title Master Report")
- `vendor` - Vendor name
- `frequency` - How often the harvest runs
- `recurring_until` - End date for the schedule
- `last_fetch` - Date/time of last fetch with any error messages
- `enabled` - "Yes" or "No" (or "Yes (Auto-enabled)" if script enabled it)
- `has_error` - "True" if error found, "False" if clean

### Terminal Output
The script shows progress in the terminal:
- ✓ = Success
- ✗ = Error or problem
- → = Action being taken

---

## Common Issues & Solutions

### Issue: "ChromeDriver not found"
**Solution:** Install webdriver-manager and modify the script:
```python
# At the top of the script, add:
from webdriver_manager.chrome import ChromeDriverManager

# In the setup_chrome_driver() function, change this line:
driver = webdriver.Chrome(options=chrome_options)

# To this:
driver = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
```

### Issue: "Login failed" or "Elements not found"
**Possible causes:**
1. Wrong username/password/MFA code
2. LibInsight changed their login page structure
3. Internet connection issue

**Solution:** 
- Double-check credentials
- Make sure you're using the current MFA code (they expire quickly!)
- Check if you can log in manually at acaweb.libinsight.com

### Issue: "Table not found" on a page
**Possible causes:**
1. Wrong dataset_id or platform_id
2. Page hasn't loaded yet
3. No SUSHI schedules exist for that platform

**Solution:**
- Verify the IDs by visiting the page manually in LibInsight
- The script will continue with other datasets even if one fails

### Issue: Modal/popup doesn't open for auto-enable
**Possible causes:**
1. Button selector changed in LibInsight
2. JavaScript not fully loaded

**Solution:**
- Add longer wait times (I can help with this)
- Temporarily disable auto-enable and just use for data extraction

---

## Making Edits to the Script

### Adding More Datasets
**Location:** Around line 25-35 in the `DATASETS_TO_CHECK` list

**Steps:**
1. Find the section that looks like:
```python
DATASETS_TO_CHECK = [
    (38772, 151, "aca JSTOR", "Alice Lloyd College"),
]
```

2. Before the closing `]`, add a new line with your dataset info:
```python
DATASETS_TO_CHECK = [
    (38772, 151, "aca JSTOR", "Alice Lloyd College"),
    (NEW_DATASET_ID, NEW_PLATFORM_ID, "Dataset Name", "Library Name"),  # ← Add here
]
```

3. Replace `NEW_DATASET_ID`, `NEW_PLATFORM_ID`, etc. with your actual values

4. **Important:** Keep the comma at the end of each line except the last one!

### Changing the Output Filename
**Location:** Around line 40, find:
```python
OUTPUT_CSV = "SUSHI_harvest_status_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
```

**To change the prefix from "SUSHI_harvest_status":**
Replace `"SUSHI_harvest_status_"` with your desired prefix, like:
```python
OUTPUT_CSV = "MyLibrary_SUSHI_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
```

### Adjusting Wait Times
If the script is running too fast or timing out:

**Location:** Look for lines with `time.sleep(X)` or `WebDriverWait(driver, X)`

**To slow down:**
```python
time.sleep(2)  # Change 2 to a bigger number like 5
```

**To wait longer for elements:**
```python
WebDriverWait(driver, 10)  # Change 10 to a bigger number like 20
```

---

## Next Steps

### Option 1: Just Extract Data (Read-Only)
Keep `AUTO_ENABLE_DISABLED_HARVESTS = False` and use the script to generate reports.

### Option 2: Auto-Enable Disabled Harvests
Set `AUTO_ENABLE_DISABLED_HARVESTS = True` to automatically re-enable any disabled schedules.

### Option 3: Schedule Regular Runs
You can set up this script to run automatically:
- **Windows:** Use Task Scheduler
- **Mac/Linux:** Use cron jobs

(I can provide instructions for this if you'd like!)

---

## Getting Help

If you encounter any issues:
1. Copy the error message from the terminal
2. Note which dataset/platform was being processed
3. Share these details with me and I can help troubleshoot!

---

## Script Structure (For Learning)

The script is organized into these main sections:

1. **Configuration** (Lines 1-50) - Settings you can change
2. **Helper Functions** (Lines 52-340) - Individual tasks like "login" or "extract data"
3. **Main Script** (Lines 342-end) - Puts everything together

Each function has comments explaining what it does. This makes it easier to:
- Understand how each part works
- Make small changes without breaking other parts
- Learn Python by seeing working examples

---

## Version Control Tips (GitHub)

If you're tracking this script in GitHub:

1. **First commit:**
```bash
git add sushi_harvest_tracker.py
git commit -m "Add initial SUSHI harvest tracker script"
git push
```

2. **After making edits:**
```bash
git add sushi_harvest_tracker.py
git commit -m "Update dataset list to include Bloomsbury"
git push
```

3. **Before major changes:**
```bash
git checkout -b test-auto-enable
# Make your changes
git add sushi_harvest_tracker.py
git commit -m "Test auto-enable functionality"
# If it works well:
git checkout main
git merge test-auto-enable
```

This keeps a history of your changes so you can always go back if needed!
