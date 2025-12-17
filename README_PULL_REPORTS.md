# LibInsight Usage Reports Generator - Script 1

## Overview

This script retrieves usage statistics from the LibInsight API and generates CSV reports for consortium member libraries.

## What's Been Implemented (Version 1.0 - Foundation)

### ✅ Completed Features:
1. **Configuration Management**
   - Fiscal year settings (FY 2024-2025)
   - Dataset definitions (JSTOR, ASP, Newsbank, Grove, Bloomsbury)
   - File path configurations
   
2. **Authentication**
   - OAuth 2.0 integration using existing `springshare_auth.py`
   - Automatic access token retrieval
   
3. **Platform Mapping**
   - Reads `libinsight-platforms.csv`
   - Filters active platforms (excludes inactive ABC-CLIO)
   - Groups platforms by library
   
4. **Report Structure**
   - Platform-specific report generation (individual library reports)
   - Dataset summary report generation (consortium-wide totals)
   - Correct CSV formatting matching LibInsight output
   
5. **Logging & Error Handling**
   - Detailed logging to both file and console
   - Error handling for missing files, API issues
   - Timestamped log files in `logs/` directory

### 🚧 To Be Implemented (Next Steps):

1. **API Data Retrieval** - This is the main task remaining
   - Need to call the actual LibInsight API endpoints
   - Retrieve usage statistics for each title
   - Parse the API response and extract usage metrics
   
2. **Data Aggregation**
   - Sum up statistics across titles for summary reports
   - Handle Bloomsbury + ABC-CLIO consolidation
   
3. **CSV Data Population**
   - Fill in actual usage numbers (currently creates empty reports)
   - Format numbers correctly (commas for thousands, etc.)

## Files Required

### Input Files:
- `libinsight-platforms.csv` - Platform/library mappings (provided ✅)
- `.env` - Environment file with API credentials
- `springshare_auth.py` - OAuth authentication module (existing ✅)

### Output Files (Generated):
- Individual library reports: `{library}_{vendor}_{FY}.csv`
- Dataset summaries: `{vendor}PlatformsSummary_{FY}.csv`
- Log files: `logs/libinsight_reports_{timestamp}.log`

## Setup Instructions

### 1. Environment Configuration

Create or edit your `.env` file with LibInsight API credentials:

```bash
# LibInsight API OAuth 2.0 Credentials
LI_KEY=your_client_id_here
LI_SECRET=your_client_secret_here
```

**Where to find these credentials:**
1. Log in to LibInsight at https://acaweb.libinsight.com
2. Go to Admin → Widgets & APIs → Manage API Authentication
3. Your application should show the Client ID (LI_KEY) and Client Secret (LI_SECRET)

### 2. Required Python Packages

Install dependencies (these should already be installed from your SUSHI tracker):

```bash
pip install requests pandas python-dotenv --break-system-packages
```

### 3. File Structure

Make sure these files are in the same directory:

```
libinsight_usage_reports.py  (main script)
springshare_auth.py          (authentication)
libinsight-platforms.csv     (platform mappings)
.env                         (credentials)
```

## Running the Script

### IMPORTANT: Test First!

Before running the full script, run the foundation test to make sure everything is set up correctly:

```bash
python test_foundation.py
```

This will verify:
- ✓ Environment variables are set
- ✓ Authentication works
- ✓ Platform mappings load correctly
- ✓ Output structure is valid

**If all tests pass**, you're ready to run the full script.

### Basic Usage:

```bash
python libinsight_usage_reports.py
```

### What Happens:

1. Script loads configuration
2. Reads platform mappings from CSV
3. Gets API access token (OAuth 2.0)
4. Processes each dataset (JSTOR, ASP, Newsbank, Grove, Bloomsbury)
5. Generates CSV reports in `usage_reports/` directory
6. Logs all activity to `logs/` directory

### Expected Output:

```
usage_reports/
├── aspPlatformsSummary_2425.csv
├── alc_asp_2425.csv
├── berea_asp_2425.csv
├── ... (more library reports)
├── jstorPlatformsSummary_2425.csv
├── alc_jstor_2425.csv
└── ... (etc for all datasets)
```

### CLI flags:

```bash
# Just Oxford Grove summaries for all libraries (overview + summary)
python libinsight_usage_reports.py --datasets grove --reports overview

# Everything for Berea across all datasets
python libinsight_usage_reports.py --libraries berea

# Top100 for just ASP and Newsbank datasets (all libraries)
python libinsight_usage_reports.py --datasets asp,newsbank --reports top100

# Generate ONLY BCLA summaries for all datasets (fastest)
python libinsight_usage_reports.py --reports summary

# Generate ONLY the Oxford Grove BCLA summary
python libinsight_usage_reports.py --datasets grove --reports summary

# Generate BCLA summaries for ASP and Newsbank only
python libinsight_usage_reports.py --datasets asp,newsbank --reports summary

# Everything (original behavior - includes summaries)
python libinsight_usage_reports.py
```

## Current Limitations

**IMPORTANT:** This is Version 1.0 (Foundation Only)

The script currently creates the report **structure** but does not yet populate them with actual usage data from the API. Here's what happens now:

- ✅ Creates all the correct CSV files
- ✅ Sets up correct column headers
- ✅ Generates proper filenames
- ❌ Reports contain empty/zero data (API calls not yet implemented)

## Next Development Phase

The next step is to implement the actual API data retrieval. This will involve:

1. **Understanding the API Response Format**
   - Test API endpoint with sample calls
   - Document the JSON structure returned
   
2. **Implementing `get_title_usage_stats()`**
   - Make actual API calls to retrieve usage data
   - Parse the JSON response
   - Extract the metrics we need
   
3. **Populating Report Data**
   - Fill in the CSV files with real numbers
   - Calculate totals for summary reports
   - Handle special cases (Bloomsbury/ABC-CLIO)

## Testing Strategy

### Phase 1: Structure Test (Current)
- Run the script to verify file creation
- Check that all expected CSVs are generated
- Verify column headers match requirements

### Phase 2: API Integration (Next)
- Test with ONE dataset first (recommend starting with ASP - smallest dataset)
- Verify API responses are correct
- Check data appears in CSV files

### Phase 3: Full Dataset Testing
- Run all five datasets
- Verify totals are calculated correctly
- Test Bloomsbury/ABC-CLIO consolidation

## Troubleshooting

### Issue: "Platform mappings file not found"
**Solution:** Make sure `libinsight-platforms.csv` is in the same directory as the script

### Issue: "Failed to obtain access token"
**Solution:** 
1. Check that `.env` file exists and has correct credentials
2. Verify LI_KEY and LI_SECRET are valid (not CLIENT_ID/CLIENT_SECRET!)
3. Check that `springshare_auth.py` is present
4. Run `python test_foundation.py` to diagnose the issue

### Issue: Script runs but creates empty reports
**Expected:** This is normal for Version 1.0. API integration comes in the next phase.

## Questions for Next Steps

Before we implement the API data retrieval, we need to:

1. **Test the API endpoints manually** to see what data structure is returned
2. **Verify which API endpoint gives us the usage statistics** we need
3. **Understand the data types** for Title Master Reports vs Database Master Reports

Would you like to proceed with API integration testing next?

## Version History

- **v1.0** (Current) - Foundation: File structure, authentication, report templates
- **v2.0** (Planned) - API integration: Actual data retrieval and population
- **v3.0** (Planned) - Polish: Error handling, retry logic, optimization

---

**Created:** December 2024  
**Author:** Angie (ACA Systems Librarian)  
**Purpose:** Automate LibInsight usage report generation for consortium libraries
