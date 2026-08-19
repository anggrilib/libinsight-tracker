"""Verify zip files produced by create_usage_zips.py against a reference set.

A zip can be non-empty and still be wrong: a subdirectory silently skipped, a
nested path flattened, a file dropped. This compares every archive member by
name, CRC32 and uncompressed size, so those failures are caught instead of
being eyeballed.

Usage:
    python verify_usage_zips.py
    python verify_usage_zips.py --reference usage_reports_2425 --candidate usage_reports
    python verify_usage_zips.py --strict-bytes

Exits 0 when every zip matches, 1 otherwise, so it can gate a release.
"""

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

from create_usage_zips import FY_SHORT

# Directory holding the freshly generated zips.
CANDIDATE_DIR = "usage_reports"

# Directory holding the known-good zips to compare against.
REFERENCE_DIR = f"usage_reports_{FY_SHORT}"

# Comparison outcomes for a single pair of zips.
IDENTICAL = "identical"      # same bytes
EQUIVALENT = "equivalent"    # same members, different archive metadata
DIFFERENT = "different"      # members added, removed or changed
UNREADABLE = "unreadable"    # not a valid zip, or could not be opened


def sha256(path):
    """Return the hex SHA-256 of a file, read in chunks so size is not a limit."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_members(path):
    """Return the archive's members as {name: ZipInfo}."""
    with zipfile.ZipFile(path) as archive:
        return {info.filename: info for info in archive.infolist()}


def manifest(members):
    """
    Reduce members to the facts that define the payload: name, checksum, size.

    Archive metadata (timestamps, member order, compression settings) is
    deliberately excluded -- it varies between runs without changing what a
    consumer extracts.
    """
    return sorted((name, info.CRC, info.file_size) for name, info in members.items())


def describe_metadata_difference(ref_members, cand_members):
    """Explain why two archives with identical payloads are not byte-identical."""
    reasons = []

    if list(ref_members) != list(cand_members):
        reasons.append("member order differs")
    if any(ref_members[n].date_time != cand_members[n].date_time for n in ref_members):
        reasons.append("member timestamps differ")
    if any(ref_members[n].compress_type != cand_members[n].compress_type
           for n in ref_members):
        reasons.append("compression method differs")
    if any(ref_members[n].compress_size != cand_members[n].compress_size
           for n in ref_members):
        reasons.append("compressed sizes differ")

    return reasons or ["archive metadata differs"]


def describe_payload_difference(ref_members, cand_members):
    """List every member that was added, removed or changed."""
    ref_facts = {n: (i.CRC, i.file_size) for n, i in ref_members.items()}
    cand_facts = {n: (i.CRC, i.file_size) for n, i in cand_members.items()}
    lines = []

    for name in sorted(set(ref_facts) - set(cand_facts)):
        lines.append(f"missing from candidate: {name}")
    for name in sorted(set(cand_facts) - set(ref_facts)):
        lines.append(f"unexpected in candidate: {name}")
    for name in sorted(set(ref_facts) & set(cand_facts)):
        if ref_facts[name] != cand_facts[name]:
            ref_crc, ref_size = ref_facts[name]
            cand_crc, cand_size = cand_facts[name]
            lines.append(
                f"changed: {name} "
                f"(reference CRC {ref_crc:08x}/{ref_size} bytes, "
                f"candidate CRC {cand_crc:08x}/{cand_size} bytes)"
            )

    return lines


def compare_zip(reference_path, candidate_path):
    """Compare one pair of zips. Returns (outcome, detail_lines)."""
    try:
        ref_members = read_members(reference_path)
        cand_members = read_members(candidate_path)
    except (zipfile.BadZipFile, OSError) as error:
        return UNREADABLE, [str(error)]

    if manifest(ref_members) != manifest(cand_members):
        return DIFFERENT, describe_payload_difference(ref_members, cand_members)

    try:
        same_bytes = sha256(reference_path) == sha256(candidate_path)
    except OSError as error:
        # The payloads already matched, so report the equivalence we proved
        # rather than failing the whole run over an unreadable byte stream.
        return EQUIVALENT, [f"could not compare bytes: {error}"]

    if same_bytes:
        return IDENTICAL, []
    return EQUIVALENT, describe_metadata_difference(ref_members, cand_members)


def parse_args():
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Compare generated usage-report zips against a known-good set."
    )
    parser.add_argument(
        "--candidate", default=CANDIDATE_DIR,
        help=f"directory holding the newly generated zips (default: {CANDIDATE_DIR})",
    )
    parser.add_argument(
        "--reference", default=REFERENCE_DIR,
        help=f"directory holding the known-good zips (default: {REFERENCE_DIR})",
    )
    parser.add_argument(
        "--strict-bytes", action="store_true",
        help="treat a metadata-only difference as a failure, not just the payload",
    )
    return parser.parse_args()


def report_roster_problems(only_reference, only_candidate):
    """Print zips present on one side only. Returns True if any were found."""
    for name in only_reference:
        print(f"  MISSING  {name} -- in reference but was not generated")
    for name in only_candidate:
        print(f"  EXTRA    {name} -- generated but not in reference")
    return bool(only_reference or only_candidate)


def compare_all(reference_zips, candidate_zips):
    """Compare every zip present in both directories, printing anything notable."""
    outcomes = {IDENTICAL: [], EQUIVALENT: [], DIFFERENT: [], UNREADABLE: []}

    for name in sorted(set(reference_zips) & set(candidate_zips)):
        outcome, details = compare_zip(reference_zips[name], candidate_zips[name])
        outcomes[outcome].append(name)

        if outcome == IDENTICAL:
            continue

        marker = "!" if outcome in (DIFFERENT, UNREADABLE) else "~"
        print(f"  {marker} {name} ({outcome})")
        for line in details:
            print(f"      {line}")
        print()

    return outcomes


def report_summary(outcomes, roster_failed, strict_bytes):
    """Print the tally and verdict. Returns True if the run should fail."""
    print(f"{'=' * 50}")
    print(f"Compared {sum(len(names) for names in outcomes.values())} zip files")
    print(f"  byte-for-byte identical : {len(outcomes[IDENTICAL])}")
    print(f"  same contents           : {len(outcomes[EQUIVALENT])}")
    print(f"  contents differ         : {len(outcomes[DIFFERENT])}")
    print(f"  unreadable              : {len(outcomes[UNREADABLE])}")

    failed = bool(
        roster_failed
        or outcomes[DIFFERENT]
        or outcomes[UNREADABLE]
        or (strict_bytes and outcomes[EQUIVALENT])
    )

    if failed:
        print("\nFAILED -- see the details above.")
    else:
        print("\nPASSED -- every zip contains exactly the expected files.")
    print(f"{'=' * 50}")

    return failed


def main():
    """Compare the two directories and report the result."""
    args = parse_args()
    base_dir = Path.cwd()
    reference_dir = base_dir / args.reference
    candidate_dir = base_dir / args.candidate

    for label, directory in (("reference", reference_dir), ("candidate", candidate_dir)):
        if not directory.is_dir():
            print(f"Error: {label} directory not found at {directory}")
            return 1

    reference_zips = {p.name: p for p in reference_dir.glob("*.zip")}
    candidate_zips = {p.name: p for p in candidate_dir.glob("*.zip")}

    print(f"Reference: {reference_dir}")
    print(f"Candidate: {candidate_dir}\n")

    roster_failed = report_roster_problems(
        sorted(set(reference_zips) - set(candidate_zips)),
        sorted(set(candidate_zips) - set(reference_zips)),
    )
    outcomes = compare_all(reference_zips, candidate_zips)

    return 1 if report_summary(outcomes, roster_failed, args.strict_bytes) else 0


if __name__ == "__main__":
    print("Usage Report Zip Verifier")
    print("=" * 50)
    sys.exit(main())
