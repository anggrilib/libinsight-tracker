#!/usr/bin/env python3
"""
LibInsight Usage Reports Generator
===================================

This script retrieves usage statistics from LibInsight API and generates CSV reports
for consortium member libraries.

Dependencies:
    - requests
    - pandas
    - python-dotenv
    - springshare_auth.py (OAuth 2.0 authentication)

Usage:
    python libinsight_usage_reports.py
"""

import os
import sys
import csv
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
import requests
import pandas as pd
from dotenv import load_dotenv

# Import the existing Springshare authentication module
from springshare_auth import SpringshareAuth

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load environment variables from .env file
load_dotenv()

# Fiscal Year Configuration
FISCAL_YEAR = {
    'start': '2024-07-01',
    'end': '2025-06-30',
    'label': '2425'  # Used in filenames
}

# Dataset Configuration
# These are the five datasets we need to process
DATASETS = {
    '38772': {
        'name': 'JSTOR',
        'abbrev': 'jstor',
        'report_type': 'Title Master Report'
    },
    '39017': {
        'name': 'Alexander Street',
        'abbrev': 'asp',
        'report_type': 'Database Master Report'
    },
    '37166': {
        'name': 'Newsbank', 
        'abbrev': 'newsbank',
        'report_type': 'Database Master Report'
    },
    '38993': {
        'name': 'Oxford Grove',
        'abbrev': 'grove',
        'report_type': 'Title Master Report'
    },
    '40156': {
        'name': 'Bloomsbury',
        'abbrev': 'bloomsbury',
        'report_type': 'Title Master Report',
        # Special note: includes ABC-CLIO platforms (inactive as of Nov 2024)
        'includes_abc_clio': True
    }
}

# Argparse Configuration
def parse_arguments():
    """
    Parse command-line arguments for selective report generation.
    
    Returns:
        argparse.Namespace: Parsed arguments with filters
    """
    parser = argparse.ArgumentParser(
        description='Generate LibInsight usage reports for consortium libraries.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all reports (default)
  python libinsight_usage_reports.py
  
  # Only Berea College, only Oxford Grove, only top 100 reports
  python libinsight_usage_reports.py --libraries berea --datasets oxford --reports top100
  
  # Multiple libraries
  python libinsight_usage_reports.py --libraries berea,alc,bcky
  
  # Only overview reports for all libraries
  python libinsight_usage_reports.py --reports overview
  
Dataset abbreviations: asp, newsbank, bloomsbury, oxford
        """
    )
    
    parser.add_argument(
        '--libraries', '-l',
        type=str,
        default=None,
        help='Comma-separated list of library abbreviations to process (e.g., "berea,alc,bcky"). Default: all libraries'
    )
    
    parser.add_argument(
        '--datasets', '-d',
        type=str,
        default=None,
        help='Comma-separated list of dataset abbreviations to process (e.g., "oxford,asp,newsbank"). Default: all datasets'
    )
    
    parser.add_argument(
        '--reports', '-r',
        type=str,
        choices=['all', 'overview', 'top100', 'summary'],
        default='all',
        help='Type of reports to generate: "all", "overview" (platform summaries), "top100" (title reports), or "summary" (BCLA consortium summaries only). Default: all'
    )
    
    args = parser.parse_args()
    
    # Process the comma-separated lists into sets for easy filtering
    filters = {
        'libraries': None,
        'datasets': None,
        'reports': args.reports
    }
    
    if args.libraries:
        # Convert comma-separated string to set of lowercase abbreviations
        filters['libraries'] = set(lib.strip().lower() for lib in args.libraries.split(','))
        
    if args.datasets:
        # Convert comma-separated string to set of lowercase abbreviations
        filters['datasets'] = set(ds.strip().lower() for ds in args.datasets.split(','))
    
    return filters

# API Configuration
API_BASE_URL = 'https://acaweb.libinsight.com/v1.0'
API_ENDPOINTS = {
    'platforms': '/e-resources/{dataset_id}/platforms',
    'overview': '/e-resources/{dataset_id}/overview',
    'title_usage': '/e-resources/{dataset_id}/titles/{title_id}'
}

# File paths
PLATFORMS_CSV = 'libinsight-platforms.csv'
OUTPUT_DIR = 'usage_reports'

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure logging to both file and console."""
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Create a timestamped log file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'libinsight_reports_{timestamp}.log'
    
    # Configure logging format
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_platform_mappings():
    """
    Load the platform mappings from libinsight-platforms.csv.
    
    Returns:
        pandas.DataFrame: Platform mappings with columns:
            - library_name
            - library_abbreviation
            - dataset_id
            - platform_id
            - report_type
            - vendor_name
            - vendor_abbreviation
    """
    try:
        logger.info(f"Loading platform mappings from {PLATFORMS_CSV}")
        df = pd.read_csv(PLATFORMS_CSV)
        logger.info(f"Loaded {len(df)} platform mappings")
        return df
    except FileNotFoundError:
        logger.error(f"Platform mappings file not found: {PLATFORMS_CSV}")
        logger.error("Please ensure libinsight-platforms.csv is in the current directory")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading platform mappings: {e}")
        sys.exit(1)

def create_output_directory():
    """Create the output directory for CSV reports if it doesn't exist."""
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(exist_ok=True)
    logger.info(f"Output directory: {output_path.absolute()}")
    return output_path

def create_library_directory(output_dir, library_abbrev):
    """
    Create a subdirectory for a specific library's reports.
    
    Args:
        output_dir (Path): Base output directory
        library_abbrev (str): Library abbreviation (e.g., 'alc', 'berea')
        
    Returns:
        Path: Library-specific directory path
    """
    library_dir = output_dir / library_abbrev
    library_dir.mkdir(exist_ok=True)
    return library_dir

def create_bcla_summaries_directory(output_dir):
    """
    Create a subdirectory for BCLA consortium-wide summary reports.
    
    Args:
        output_dir (Path): Base output directory
        
    Returns:
        Path: BCLA summaries directory path
    """
    bcla_dir = output_dir / 'bcla_summaries'
    bcla_dir.mkdir(exist_ok=True)
    return bcla_dir

def get_access_token():
    """
    Get a valid access token for LibInsight API using SpringshareAuth.
    
    Returns:
        str: Valid access token
    """
    try:
        logger.info("Obtaining LibInsight API access token...")
        
        # Create SpringshareAuth instance
        auth = SpringshareAuth()
        
        # Get token (returns dict with 'access_token', 'token_type', 'expires_in')
        token_response = auth.get_token()
        
        if not token_response:
            raise Exception("Failed to obtain token from SpringshareAuth")
        
        access_token = token_response.get('access_token')
        expires_in = token_response.get('expires_in')
        
        logger.info(f"Successfully obtained access token (expires in {expires_in} seconds)")
        return access_token
        
    except ValueError as e:
        logger.error(f"Authentication error: {e}")
        logger.error("Please check your .env file has LI_KEY and LI_SECRET set correctly")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to obtain access token: {e}")
        sys.exit(1)

def make_api_request(endpoint, access_token, params=None):
    """
    Make a request to the LibInsight API.
    
    Args:
        endpoint (str): API endpoint URL
        access_token (str): Valid OAuth access token
        params (dict, optional): Query parameters
        
    Returns:
        dict: JSON response from API
    """
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        logger.debug(f"API Request: {endpoint}")
        if params:
            logger.debug(f"Parameters: {params}")
        
        response = requests.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
        
        return response.json()
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error: {e}")
        logger.error(f"Response: {e.response.text}")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Error: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {e}")
        raise

# ============================================================================
# DATA RETRIEVAL FUNCTIONS
# ============================================================================

def get_platform_overview(dataset_id, platform_id, access_token):
    """
    Get aggregated usage overview for a specific platform.
    
    NOTE: The /overview endpoint returns ALL platforms in the dataset.
    We extract just the data for the platform_id we need.
    
    Args:
        dataset_id (str): Dataset ID
        platform_id (int): Platform ID
        access_token (str): API access token
        
    Returns:
        dict: Overview data with aggregated statistics by data_type
              Structure: { 'Book': {...stats...}, 'Journal': {...stats...}, ... }
    """
    # Construct the API endpoint
    endpoint = f"{API_BASE_URL}/e-resources/{dataset_id}/overview"
    
    # Add query parameters
    # NOTE: Do NOT include 'platforms' parameter - endpoint returns all platforms
    params = {
        'from': FISCAL_YEAR['start'],
        'to': FISCAL_YEAR['end']
    }
    
    try:
        logger.info(f"  Calling /overview endpoint...")
        response = make_api_request(endpoint, access_token, params)
        
        # Parse the response structure:
        # {
        #   "payload": {
        #     "overview_by_platforms": {
        #       "197": {              // Platform ID as key
        #         "Book": {           // Data type as key
        #           "total_item_requests": 123,
        #           ...
        #         },
        #         "Journal": {...},
        #         ...
        #       }
        #     }
        #   }
        # }
        
        if response and 'payload' in response:
            payload = response.get('payload', {})
            overview_by_platforms = payload.get('overview_by_platforms', {})
            
            # Extract data for our specific platform
            platform_data = overview_by_platforms.get(str(platform_id))
            
            if platform_data:
                # Count how many data types have data
                data_types = list(platform_data.keys())
                logger.info(f"  Got overview data for platform {platform_id}")
                logger.info(f"  Data types: {', '.join(data_types)}")
                
                return platform_data
            else:
                logger.warning(f"  Platform {platform_id} not found in /overview response")
                return None
        else:
            logger.warning(f"  /overview returned unexpected structure")
            logger.debug(f"  Response keys: {response.keys() if response else 'None'}")
            return None
        
    except Exception as e:
        logger.error(f"  Error fetching overview for platform {platform_id}: {e}")
        return None
    
def get_top_titles(dataset_id, platform_id, access_token, limit=100):
    """
    Get top titles by usage for a specific platform.
    
    Returns the top titles sorted by total_item_requests for each data type.
    
    Args:
        dataset_id (str): Dataset ID
        platform_id (int): Platform ID
        access_token (str): API access token
        limit (int): Number of top titles to retrieve per data_type (default 100)
        
    Returns:
        dict: Dictionary organized by data_type with title lists
              Structure: {
                  'Book': [...titles sorted by total_item_requests...],
                  'Journal': [...titles...],
                  ...
              }
    """
    # Define all data types to loop through
    data_types = ['Database', 'Journal', 'Book', 'Multimedia', 'Other']
    
    # Storage for all results
    all_results = {}
    
    # Construct the base endpoint
    endpoint = f"{API_BASE_URL}/e-resources/{dataset_id}/top-use-titles"
    
    logger.info(f"  Fetching top titles for platform {platform_id}...")
    
    # Loop through each data type
    for data_type in data_types:
        # Use total_item_requests to sort/rank the titles
        params = {
            'from': FISCAL_YEAR['start'],
            'to': FISCAL_YEAR['end'],
            'platform_id': platform_id,
            'data_type': data_type,
            'metric_type': 'total_item_requests',  # This determines the sorting
            'limit': limit
        }
        
        try:
            response = make_api_request(endpoint, access_token, params)
            
            # Parse the response structure:
            # {
            #   "type": "success",
            #   "payload": {
            #     "data_type": "Book",
            #     "metric_type": "total_item_requests",
            #     "top_use_titles": [ ...array of title objects... ]
            #   }
            # }
            
            if response and 'payload' in response:
                payload = response['payload']
                top_use_titles = payload.get('top_use_titles', [])
                
                if top_use_titles and len(top_use_titles) > 0:
                    first_title = top_use_titles[0]
                    
                    # DIAGNOSTIC: Log what we received
                    logger.info(f"    DIAGNOSTIC - First title fields: {list(first_title.keys())}")
                    if 'platform_id' in first_title:
                        logger.info(f"    DIAGNOSTIC - Title platform_id: {first_title.get('platform_id')} (requested: {platform_id})")
                    else:
                        logger.info(f"    DIAGNOSTIC - Title does NOT have platform_id field")
                    
                    # FILTERING LOGIC: Only keep titles that match our platform_id
                    if 'platform_id' in first_title:
                        # Filter to only this platform's titles
                        platform_titles = [
                            title for title in top_use_titles 
                            if title.get('platform_id') == platform_id
                        ]
                        
                        if len(platform_titles) > 0:
                            logger.info(f"    {data_type}: {len(platform_titles)} titles (filtered from {len(top_use_titles)} total)")
                            all_results[data_type] = platform_titles
                        else:
                            logger.info(f"    {data_type}: 0 titles for this platform (filtered out {len(top_use_titles)} from other platforms)")
                            all_results[data_type] = []
                    else:
                        # No platform_id field - cannot filter
                        logger.warning(f"    {data_type}: API returned {len(top_use_titles)} titles but no platform_id field")
                        logger.warning(f"    Cannot filter to platform {platform_id} - returning empty list")
                        all_results[data_type] = []
                else:
                    logger.info(f"    {data_type}: 0 titles")
                    all_results[data_type] = []
            else:
                all_results[data_type] = []
            
            # Small delay to avoid overwhelming API
            time.sleep(0.1)
            
        except Exception as e:
            logger.warning(f"    Error for {data_type}: {e}")
            all_results[data_type] = []
    
    # Sort each data_type's titles: primary by total_item_requests (descending), 
    # secondary by title (ascending/A-Z) to match LibInsight browser behavior
    for data_type in all_results:
        all_results[data_type].sort(
            key=lambda x: (-x.get('total_item_requests', 0), x.get('title', '').lower())
        )
    
    return all_results
    
    return all_results

def analyze_dataset_data_types(dataset_results):
    """
    Analyze which data_types have ANY usage across all libraries in a dataset.
    
    Args:
        dataset_results (dict): Dictionary keyed by library_abbrev containing their results
        
    Returns:
        set: Set of data_types that have usage across the dataset
    """
    data_types_with_usage = set()
    
    for library_abbrev, library_data in dataset_results.items():
        top_titles = library_data.get('top_titles', {})
        
        # top_titles is now just {data_type: [titles]}
        for data_type, titles in top_titles.items():
            if titles and len(titles) > 0:
                # Check if any title has non-zero usage
                for title in titles:
                    # Check various usage fields
                    usage_fields = [
                        'total_item_requests', 'unique_item_requests',
                        'total_item_investigations', 'unique_item_investigations',
                        'searches_platform', 'searches_regular'
                    ]
                    for field in usage_fields:
                        if title.get(field, 0) > 0:
                            data_types_with_usage.add(data_type)
                            break
                    if data_type in data_types_with_usage:
                        break
    
    return data_types_with_usage

def get_platform_titles(dataset_id, platform_id, access_token):
    """
    Get all titles for a specific platform using the API.
    
    Args:
        dataset_id (str): Dataset ID
        platform_id (int): Platform ID
        access_token (str): API access token
        
    Returns:
        list: List of title dictionaries from API
    """
    # Construct the API endpoint
    # This will call: /e-resources/{dataset_id}/platforms/{platform_id}/titles
    endpoint = f"{API_BASE_URL}/e-resources/{dataset_id}/platforms"
    
    try:
        # Get all platforms for the dataset
        response = make_api_request(endpoint, access_token)
        
        # Find our specific platform
        platforms = response.get('platforms', [])
        for platform in platforms:
            if platform.get('id') == platform_id:
                return platform.get('titles', [])
        
        logger.warning(f"Platform {platform_id} not found in dataset {dataset_id}")
        return []
    
    except Exception as e:
        logger.error(f"Error getting titles for platform {platform_id}: {e}")
        return []

def get_title_usage_stats(dataset_id, title_id, data_type, access_token):
    """
    Get usage statistics for a specific title.
    
    Args:
        dataset_id (str): Dataset ID
        title_id (int): Title ID
        data_type (str): Data type (Book, Database, Journal, etc.)
        access_token (str): API access token
        
    Returns:
        dict: Usage statistics for the title
    """
    # Build the endpoint for title usage
    endpoint = f"{API_BASE_URL}/e-resources/{dataset_id}/titles/{title_id}"
    
    # Set up parameters
    params = {
        'from': FISCAL_YEAR['start'],
        'to': FISCAL_YEAR['end'],
        'data_type': data_type
    }
    
    try:
        response = make_api_request(endpoint, access_token, params)
        return response
    
    except Exception as e:
        logger.error(f"Error getting usage for title {title_id}: {e}")
        return None

# ============================================================================
# REPORT GENERATION FUNCTIONS
# ============================================================================

def generate_platform_report(library_info, dataset_info, overview_data, output_dir):
    """
    Generate a CSV report for a specific library's platform usage.
    
    Args:
        library_info (dict): Library information from platform mappings
        dataset_info (dict): Dataset configuration
        overview_data (dict): Overview data from API (data_types as keys)
        output_dir (Path): Output directory (should be library-specific)
        
    Returns:
        str: Path to generated CSV file
    """
    # Create filename: {library_abbrev}_{vendor_abbrev}_{FY}.csv
    filename = f"{library_info['library_abbreviation']}_{dataset_info['abbrev']}_{FISCAL_YEAR['label']}.csv"
    filepath = output_dir / filename
    
    # Define columns for the platform overview report
    columns = [
        'Data Type',
        'Searches Platform',
        'Total Item Investigations',
        'Total Item Requests',
        'Unique Item Investigations',
        'Unique Item Requests',
        'Unique Title Investigations',
        'Unique Title Requests'
    ]
    
    try:
        # Write CSV file
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            
            # Extract data from overview response
            # Structure is: { 'Book': {...stats...}, 'Journal': {...stats...} }
            if overview_data:
                for data_type, stats in overview_data.items():
                    row = {
                        'Data Type': data_type,
                        'Searches Platform': stats.get('searches_platform', 0),
                        'Total Item Investigations': stats.get('total_item_investigations', 0),
                        'Total Item Requests': stats.get('total_item_requests', 0),
                        'Unique Item Investigations': stats.get('unique_item_investigations', 0),
                        'Unique Item Requests': stats.get('unique_item_requests', 0),
                        'Unique Title Investigations': stats.get('unique_title_investigations', 0),
                        'Unique Title Requests': stats.get('unique_title_requests', 0)
                    }
                    writer.writerow(row)
            else:
                # No data available - write a row indicating this
                logger.warning(f"  No overview data available for {filename}")
                writer.writerow({
                    'Data Type': 'No data available',
                    'Searches Platform': 0,
                    'Total Item Investigations': 0,
                    'Total Item Requests': 0,
                    'Unique Item Investigations': 0,
                    'Unique Item Requests': 0,
                    'Unique Title Investigations': 0,
                    'Unique Title Requests': 0
                })
        
        logger.info(f"  Generated: {filename}")
        return str(filepath)
    
    except Exception as e:
        logger.error(f"Error generating platform report {filename}: {e}")
        return None

def generate_top_titles_report(library_info, dataset_info, titles_data, valid_data_types, output_dir):
    """
    Generate CSV reports for top titles by usage.
    
    Creates separate files for each data_type that has usage in the dataset.
    Titles are sorted by total_item_requests and displayed once with all metrics.
    
    Args:
        library_info (dict): Library information from platform mappings
        dataset_info (dict): Dataset configuration
        titles_data (dict): Dict of titles organized by data_type (already sorted)
        valid_data_types (set): Set of data_types that should be reported for this dataset
        output_dir (Path): Output directory (should be library-specific)
        
    Returns:
        list: Paths to generated CSV files
    """
    generated_files = []
    
    # Only process data_types that are valid for this dataset
    for data_type in valid_data_types:
        if data_type not in titles_data:
            continue
        
        titles = titles_data[data_type]
        
        # Create filename: {library_abbrev}_{vendor_abbrev}_{data_type}_top100_{FY}.csv
        filename = f"{library_info['library_abbreviation']}_{dataset_info['abbrev']}_{data_type.lower()}_top100_{FISCAL_YEAR['label']}.csv"
        filepath = output_dir / filename
        
        # Define columns for top titles report (matching manual export format)
        columns = [
            'Rank',
            'Title',
            'Publisher',
            'ISBN',
            'DOI',
            'Total Item Investigations',
            'Unique Item Investigations',
            'Unique Title Investigations',
            'Total Item Requests',
            'Unique Item Requests',
            'Unique Title Requests',
            'Searches Platform',
            'Searches Regular',
            'Searches Federated',
            'Searches Automated',
            'No License',
            'Limit Exceeded'
        ]
        
        try:
            # Write CSV file
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=columns)
                writer.writeheader()
                
                # Write each title once (already sorted by total_item_requests)
                if titles and len(titles) > 0:
                    for rank, title in enumerate(titles, start=1):
                        row = {
                            'Rank': rank,
                            'Title': title.get('title', ''),
                            'Publisher': title.get('publisher', ''),
                            'ISBN': title.get('isbn', ''),
                            'DOI': title.get('doi', ''),
                            'Total Item Investigations': title.get('total_item_investigations', 0),
                            'Unique Item Investigations': title.get('unique_item_investigations', 0),
                            'Unique Title Investigations': title.get('unique_title_investigations', 0),
                            'Total Item Requests': title.get('total_item_requests', 0),
                            'Unique Item Requests': title.get('unique_item_requests', 0),
                            'Unique Title Requests': title.get('unique_title_requests', 0),
                            'Searches Platform': title.get('searches_platform', 0),
                            'Searches Regular': title.get('searches_regular', 0),
                            'Searches Federated': title.get('searches_federated', 0),
                            'Searches Automated': title.get('searches_automated', 0),
                            'No License': title.get('no_license', 0),
                            'Limit Exceeded': title.get('limit_exceeded', 0)
                        }
                        writer.writerow(row)
                else:
                    # No data for this data_type, write a placeholder
                    writer.writerow({
                        'Rank': 0,
                        'Title': f'No {data_type} titles with usage',
                        'Publisher': '',
                        'ISBN': '',
                        'DOI': '',
                        'Total Item Investigations': 0,
                        'Unique Item Investigations': 0,
                        'Unique Title Investigations': 0,
                        'Total Item Requests': 0,
                        'Unique Item Requests': 0,
                        'Unique Title Requests': 0,
                        'Searches Platform': 0,
                        'Searches Regular': 0,
                        'Searches Federated': 0,
                        'Searches Automated': 0,
                        'No License': 0,
                        'Limit Exceeded': 0
                    })
            
            logger.info(f"    Generated: {filename}")
            generated_files.append(str(filepath))
        
        except Exception as e:
            logger.error(f"    Error generating top titles report {filename}: {e}")
    
    return generated_files

def generate_dataset_summary(dataset_id, dataset_info, platform_data, bcla_summaries_dir):
    """
    Generate a dataset summary CSV report with totals for all libraries.
    
    Args:
        dataset_id (str): Dataset ID
        dataset_info (dict): Dataset configuration
        platform_data (list): List of platform summary data
        bcla_summaries_dir (Path): BCLA summaries output directory
        
    Returns:
        str: Path to generated CSV file
    """
    # Create filename: {vendor_abbrev}PlatformsSummary_{FY}.csv
    filename = f"{dataset_info['abbrev']}PlatformsSummary_{FISCAL_YEAR['label']}.csv"
    filepath = bcla_summaries_dir / filename
    
    # Determine column header based on report type
    if dataset_info['report_type'] == 'Title Master Report':
        count_column = '# of Titles'
    else:  # Database Master Report
        count_column = '# of Databases'
    
    columns = [
        'Library',
        'Platform Name',
        'Searches Platform',
        'Total Item Investigations',
        'Total Item Requests',
        'Unique Item Investigations',
        'Unique Item Requests',
        'Unique Title Investigations',
        'Unique Title Requests'
    ]
    
    try:
        # Calculate totals
        searches_platform_total = sum(p.get('searches_platform', 0) for p in platform_data)
        total_item_investigations_total = sum(p.get('total_item_investigations', 0) for p in platform_data)
        total_item_requests_total = sum(p.get('total_item_requests', 0) for p in platform_data)
        unique_item_investigations_total = sum(p.get('unique_item_investigations', 0) for p in platform_data)
        unique_item_requests_total = sum(p.get('unique_item_requests', 0) for p in platform_data)
        unique_title_investigations_total = sum(p.get('unique_title_investigations', 0) for p in platform_data)
        unique_title_requests_total = sum(p.get('unique_title_requests', 0) for p in platform_data)
        
        # Write CSV file
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            
            # Write each platform's data
            for data in platform_data:
                row = {
                    'Library': data.get('library_name', ''),
                    'Platform Name': data.get('platform_name', ''),
                    'Searches Platform': data.get('searches_platform', 0),
                    'Total Item Investigations': data.get('total_item_investigations', 0),
                    'Total Item Requests': data.get('total_item_requests', 0),
                    'Unique Item Investigations': data.get('unique_item_investigations', 0),
                    'Unique Item Requests': data.get('unique_item_requests', 0),
                    'Unique Title Investigations': data.get('unique_title_investigations', 0),
                    'Unique Title Requests': data.get('unique_title_requests', 0)
                }
                writer.writerow(row)
            
            # Write TOTAL row
            total_row = {
                'Library': 'TOTAL',
                'Platform Name': 'All Platforms',
                'Searches Platform': searches_platform_total,
                'Total Item Investigations': total_item_investigations_total,
                'Total Item Requests': total_item_requests_total,
                'Unique Item Investigations': unique_item_investigations_total,
                'Unique Item Requests': unique_item_requests_total,
                'Unique Title Investigations': unique_title_investigations_total,
                'Unique Title Requests': unique_title_requests_total
            }
            writer.writerow(total_row)
        
        logger.info(f"Generated dataset summary: {filename}")
        return str(filepath)
    
    except Exception as e:
        logger.error(f"Error generating dataset summary {filename}: {e}")
        return None
    
def generate_combined_top_titles_summary(dataset_id, dataset_info, dataset_library_results, valid_data_types, bcla_summaries_dir):
    """
    Generate combined top 100 titles reports for the entire dataset (all platforms).
    
    This creates consortium-wide reports showing the top titles across all libraries.
    
    Args:
        dataset_id (str): Dataset ID
        dataset_info (dict): Dataset configuration
        dataset_library_results (dict): Dictionary of all library results
        valid_data_types (set): Set of data_types that should be reported
        bcla_summaries_dir (Path): BCLA summaries output directory
        
    Returns:
        list: Paths to generated CSV files
    """
    generated_files = []
    
    logger.info("\nGenerating combined top 100 titles summaries...")
    
    # Aggregate titles from all libraries by data_type
    combined_titles = {}
    
    # Collect all titles from all libraries
    for library_abbrev, library_data in dataset_library_results.items():
        top_titles_data = library_data.get('top_titles_data', {})
        
        for data_type, titles in top_titles_data.items():
            if data_type not in combined_titles:
                combined_titles[data_type] = {}
            
            # Add each title to the combined dict, using title name as key
            # This automatically deduplicates and aggregates usage
            for title in titles:
                title_key = title.get('title', '')
                if not title_key:
                    continue
                
                if title_key not in combined_titles[data_type]:
                    # First time seeing this title - copy it
                    combined_titles[data_type][title_key] = title.copy()
                else:
                    # Title exists - aggregate the usage metrics
                    existing = combined_titles[data_type][title_key]
                    for metric in ['total_item_investigations', 'unique_item_investigations', 
                                   'unique_title_investigations', 'total_item_requests',
                                   'unique_item_requests', 'unique_title_requests',
                                   'searches_platform', 'searches_regular', 'searches_federated',
                                   'searches_automated', 'no_license', 'limit_exceeded']:
                        existing[metric] = existing.get(metric, 0) + title.get(metric, 0)
    
    # Now generate reports for each data_type
    for data_type in valid_data_types:
        if data_type not in combined_titles or not combined_titles[data_type]:
            continue
        
        # Convert dict to list and sort by total_item_requests
        titles_list = list(combined_titles[data_type].values())
        titles_list.sort(
            key=lambda x: (-x.get('total_item_requests', 0), x.get('title', '').lower())
        )
        
        # Limit to top 100
        titles_list = titles_list[:100]
        
        # Create filename: {vendor_abbrev}_combined_{data_type}_top100_{FY}.csv
        filename = f"{dataset_info['abbrev']}_combined_{data_type.lower()}_top100_{FISCAL_YEAR['label']}.csv"
        filepath = bcla_summaries_dir / filename
        
        # Define columns
        columns = [
            'Rank',
            'Title',
            'Publisher',
            'ISBN',
            'DOI',
            'Total Item Investigations',
            'Unique Item Investigations',
            'Unique Title Investigations',
            'Total Item Requests',
            'Unique Item Requests',
            'Unique Title Requests',
            'Searches Platform',
            'Searches Regular',
            'Searches Federated',
            'Searches Automated',
            'No License',
            'Limit Exceeded'
        ]
        
        try:
            # Write CSV file
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=columns)
                writer.writeheader()
                
                for rank, title in enumerate(titles_list, start=1):
                    row = {
                        'Rank': rank,
                        'Title': title.get('title', ''),
                        'Publisher': title.get('publisher', ''),
                        'ISBN': title.get('isbn', ''),
                        'DOI': title.get('doi', ''),
                        'Total Item Investigations': title.get('total_item_investigations', 0),
                        'Unique Item Investigations': title.get('unique_item_investigations', 0),
                        'Unique Title Investigations': title.get('unique_title_investigations', 0),
                        'Total Item Requests': title.get('total_item_requests', 0),
                        'Unique Item Requests': title.get('unique_item_requests', 0),
                        'Unique Title Requests': title.get('unique_title_requests', 0),
                        'Searches Platform': title.get('searches_platform', 0),
                        'Searches Regular': title.get('searches_regular', 0),
                        'Searches Federated': title.get('searches_federated', 0),
                        'Searches Automated': title.get('searches_automated', 0),
                        'No License': title.get('no_license', 0),
                        'Limit Exceeded': title.get('limit_exceeded', 0)
                    }
                    writer.writerow(row)
            
            logger.info(f"  Generated combined summary: {filename}")
            generated_files.append(str(filepath))
        
        except Exception as e:
            logger.error(f"  Error generating combined summary {filename}: {e}")
    
    return generated_files

# ============================================================================
# MAIN PROCESSING FUNCTIONS
# ============================================================================

def process_dataset(dataset_id, dataset_info, platform_mappings, access_token, output_dir, filters):
    """
    Process a single dataset and generate all required reports.
    
    This function now:
    1. Collects data from ALL libraries first
    2. Determines which data_types have usage across the dataset
    3. Generates reports only for data_types with usage
    
    Args:
        dataset_id (str): Dataset ID
        dataset_info (dict): Dataset configuration
        platform_mappings (pd.DataFrame): Platform mappings
        access_token (str): API access token
        output_dir (Path): Base output directory path
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing Dataset: {dataset_info['name']} (ID: {dataset_id})")
    logger.info(f"{'='*60}")
    
    # Filter platforms for this dataset
    dataset_platforms = platform_mappings[
        platform_mappings['dataset_id'] == int(dataset_id)
    ]
    
    # Exclude inactive ABC-CLIO platforms
    active_platforms = dataset_platforms[
        ~dataset_platforms['report_type'].str.contains('inactive', case=False, na=False)
    ]
    
    logger.info(f"Found {len(active_platforms)} active platforms for this dataset")
    
    # Storage for all library data in this dataset
    dataset_library_results = {}
    
    # Storage for dataset summary data
    platform_summary_data = []
    
    # Create BCLA summaries directory
    bcla_summaries_dir = create_bcla_summaries_directory(output_dir)
    
    # PHASE 1: Collect data from ALL libraries
    logger.info("\nPHASE 1: Collecting data from all libraries...")

    # Get list of libraries to process
    libraries_to_process = active_platforms['library_abbreviation'].unique()
    
    # Apply library filter if specified
    if filters['libraries']:
        libraries_to_process = [lib for lib in libraries_to_process 
                               if lib.lower() in filters['libraries']]
        logger.info(f"Filtering to libraries: {', '.join(libraries_to_process)}")
    
    for library_abbrev in libraries_to_process:
        library_platforms = active_platforms[
            active_platforms['library_abbreviation'] == library_abbrev
        ]
        
        # Get library info from first row
        library_info = library_platforms.iloc[0].to_dict()
        library_name = library_info['library_name']
        platform_id = library_info['platform_id']
        
        logger.info(f"\nCollecting: {library_name} ({library_abbrev})")
        
        # Get overview data from API
        overview_data = get_platform_overview(dataset_id, platform_id, access_token)
        
        # Get top titles data from API (skip if only generating summaries)
        if filters['reports'] != 'summary':
            top_titles_data = get_top_titles(dataset_id, platform_id, access_token, limit=100)
        else:
            top_titles_data = {}  # Empty dict for summary mode        
        
        # Store results for this library
        dataset_library_results[library_abbrev] = {
            'library_info': library_info,
            'library_name': library_name,
            'platform_id': platform_id,
            'overview_data': overview_data,
            'top_titles_data': top_titles_data
        }
        
        # Calculate totals for summary
        searches_platform = 0
        total_item_investigations = 0
        total_item_requests = 0
        unique_item_investigations = 0
        unique_item_requests = 0
        unique_title_investigations = 0
        unique_title_requests = 0
        
        if overview_data:
            # Sum across all data types
            # Structure is: { 'Book': {...stats...}, 'Journal': {...stats...} }
            # underscore represents 'data_type' for dictionary keys
            for _, stats in overview_data.items():
                searches_platform += stats.get('searches_platform', 0)
                total_item_investigations += stats.get('total_item_investigations', 0)
                total_item_requests += stats.get('total_item_requests', 0)
                unique_item_investigations += stats.get('unique_item_investigations', 0)
                unique_item_requests += stats.get('unique_item_requests', 0)
                unique_title_investigations += stats.get('unique_title_investigations', 0)
                unique_title_requests += stats.get('unique_title_requests', 0)
        
        # Add to summary data for consortium report
        platform_summary_data.append({
            'library_name': library_name,
            'platform_name': f"{library_name} - {dataset_info['name']}",
            'searches_platform': searches_platform,
            'total_item_investigations': total_item_investigations,
            'total_item_requests': total_item_requests,
            'unique_item_investigations': unique_item_investigations,
            'unique_item_requests': unique_item_requests,
            'unique_title_investigations': unique_title_investigations,
            'unique_title_requests': unique_title_requests
        })        
        # Add a small delay between libraries
        time.sleep(0.5)
    
    # PHASE 2: Analyze which data_types have usage across the dataset (skip if only summaries)
    if filters['reports'] != 'summary':
        logger.info("\nPHASE 2: Analyzing dataset-wide data_types with usage...")
        
        # Create a simplified structure for analysis
        analysis_data = {}
        for lib_abbrev, lib_data in dataset_library_results.items():
            analysis_data[lib_abbrev] = {
                'top_titles': lib_data['top_titles_data']
            }
        
        valid_data_types = analyze_dataset_data_types(analysis_data)
        
        if valid_data_types:
            logger.info(f"Data types with usage in this dataset: {', '.join(sorted(valid_data_types))}")
        else:
            logger.warning("No data types with usage found in this dataset")
    else:
        logger.info("\nPHASE 2: Skipping data type analysis (summary mode)")
        valid_data_types = set()  # Empty set for summary mode
    
    # PHASE 3: Generate reports for each library (skip if only generating summaries)
    if filters['reports'] != 'summary':
        logger.info("\nPHASE 3: Generating library reports...")
        
        for library_abbrev, library_data in dataset_library_results.items():
            library_info = library_data['library_info']
            library_name = library_data['library_name']
            overview_data = library_data['overview_data']
            top_titles_data = library_data['top_titles_data']
            
            logger.info(f"\nGenerating reports: {library_name} ({library_abbrev})")
            
            # Create library-specific directory
            library_dir = create_library_directory(output_dir, library_abbrev)
            
            # Generate platform overview report (if requested)
            if filters['reports'] in ['all', 'overview']:
                generate_platform_report(
                    library_info,
                    dataset_info,
                    overview_data,
                    library_dir
                )
            
            # Generate top titles reports (if requested and data available)
            if filters['reports'] in ['all', 'top100']:
                if valid_data_types and top_titles_data:
                    generate_top_titles_report(
                        library_info,
                        dataset_info,
                        top_titles_data,
                        valid_data_types,
                        library_dir
                    )
                else:
                    logger.warning(f"  No valid data types to report for {library_name}")
    else:
        logger.info("\nPHASE 3: Skipping individual library reports (summary mode)")
    
    # Generate dataset summary report (goes to bcla_summaries directory)
    if filters['reports'] == 'summary':
        logger.info("\nGenerating BCLA consortium summary...")
    generate_dataset_summary(
        dataset_id,
        dataset_info,
        platform_summary_data,
        bcla_summaries_dir
    )
    
    # Generate combined top 100 titles summaries (skip if only overview reports requested)
    if filters['reports'] in ['all', 'top100', 'summary'] and valid_data_types:
        generate_combined_top_titles_summary(
            dataset_id,
            dataset_info,
            dataset_library_results,
            valid_data_types,
            bcla_summaries_dir
        )

    logger.info(f"\nCompleted dataset: {dataset_info['name']}")

def main():
    """Main execution function."""
    logger.info("\n" + "="*60)
    logger.info("LibInsight Usage Reports Generator")
    logger.info("="*60)
    logger.info(f"Fiscal Year: {FISCAL_YEAR['start']} to {FISCAL_YEAR['end']}")
    logger.info(f"Report Label: FY{FISCAL_YEAR['label']}")
    logger.info("")

    # Parse command-line arguments
    filters = parse_arguments()
    
    # Log active filters
    if filters['libraries']:
        logger.info(f"Library filter: {', '.join(sorted(filters['libraries']))}")
    if filters['datasets']:
        logger.info(f"Dataset filter: {', '.join(sorted(filters['datasets']))}")
    logger.info(f"Report types: {filters['reports']}")
    logger.info("")
    
    # Step 1: Create output directory
    output_dir = create_output_directory()
    
    # Step 2: Load platform mappings
    platform_mappings = load_platform_mappings()
    
    # Step 3: Get API access token
    access_token = get_access_token()
    
    # Step 4: Process each dataset
    for dataset_id, dataset_info in DATASETS.items():
        # Apply dataset filter if specified
        if filters['datasets'] and dataset_info['abbrev'].lower() not in filters['datasets']:
            logger.info(f"Skipping dataset: {dataset_info['name']} (filtered out)")
            continue
            
        try:
            process_dataset(
                dataset_id,
                dataset_info,
                platform_mappings,
                access_token,
                output_dir,
                filters  # <-- ADD THIS
            )
        except Exception as e:
            logger.error(f"Error processing dataset {dataset_id}: {e}")
            logger.exception("Full traceback:")
            continue
    
    logger.info("\n" + "="*60)
    logger.info("Report Generation Complete!")
    logger.info(f"Output directory: {output_dir.absolute()}")
    logger.info("="*60)

# ============================================================================
# SCRIPT ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\nScript interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
