"""Create zip files from usage_reports."""

import zipfile
from pathlib import Path

# Update before outputting new zip files each FY
FY_SHORT = 2526

def create_library_zip_files():
    """
    Creates zip files for each library directory in usage_reports.
    Each zip file will be named [library]_[FY]_stats.zip and placed in the usage_reports directory.
    """
    # Define the base directory (where the script is run from)
    base_dir = Path.cwd()  # Current working directory (should be libinsight-tracker)

    # Define the usage_reports directory path
    usage_reports_dir = base_dir / "usage_reports"

    # Check if usage_reports directory exists
    if not usage_reports_dir.exists():
        print(f"Error: usage_reports directory not found at {usage_reports_dir}")
        return

    print(f"Processing directories in: {usage_reports_dir}\n")

    # Get all subdirectories in usage_reports (these are the library directories)
    library_dirs = [d for d in usage_reports_dir.iterdir() if d.is_dir()]

    # Sort the directories alphabetically for consistent processing
    library_dirs.sort()

    # Counter for successful zip creations
    success_count = 0

    # Process each library directory
    for library_dir in library_dirs:
        library_name = library_dir.name  # Get just the directory name (e.g., 'alc', 'berea')

        # Define the zip file name and path
        zip_filename = f"{library_name}_{FY_SHORT}_stats.zip"
        zip_filepath = usage_reports_dir / zip_filename  # Zip will be in usage_reports directory

        try:
            # Create the zip file
            print(f"Creating {zip_filename}...")

            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Walk every file in the library directory, in sorted order so
                # repeated runs produce identical zips
                for file_path in sorted(library_dir.rglob("*")):
                    if not file_path.is_file():
                        continue

                    # Calculate the relative path from the library directory
                    # This preserves the directory structure inside the zip
                    arcname = file_path.relative_to(library_dir)

                    # Add file to zip with its relative path
                    zipf.write(file_path, arcname)

        except OSError as e:
            # zipfile creates the archive as soon as it opens, so a failure
            # part-way through leaves an incomplete zip behind. Delete it: a
            # truncated zip still looks like a finished file on disk and could
            # be uploaded by mistake.
            print(f"  ✗ Error creating zip for {library_name}: {e}")

            if zip_filepath.exists():
                try:
                    zip_filepath.unlink()
                    print(f"    Deleted partial zip {zip_filename}")
                except OSError as cleanup_error:
                    print(f"    WARNING: could not delete partial zip "
                          f"{zip_filename}: {cleanup_error}")
                    print("    Delete it manually before uploading.")

            print("    Continuing to the next library.\n")
            continue

        # The zip closed cleanly, so it is complete even if stat() fails below.
        # Keep this out of the try above so a stat error never deletes a good zip.
        try:
            zip_size = zip_filepath.stat().st_size / 1024  # Size in KB
            print(f"  ✓ Created successfully ({zip_size:.1f} KB)\n")
        except OSError as e:
            print(f"  ✓ Created successfully (size unavailable: {e})\n")

        success_count += 1

    # Print summary
    print(f"\n{'='*50}")
    print(f"Summary: Successfully created {success_count} of {len(library_dirs)} zip files")
    print(f"{'='*50}")

if __name__ == "__main__":
    print("Library Directory Zip File Creator")
    print("=" * 50)
    create_library_zip_files()
