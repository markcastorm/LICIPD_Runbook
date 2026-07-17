"""
LICIPD pipeline entry point.

Usage:
    python main.py

Runs the full pipeline:
  1. Scrape LIC India Public Disclosure PDFs
  2. Extract 56 financial fields from 4 PDF types
  3. Append new quarter(s) to Master_Data/Master_LICIPD_DATA.csv
  4. Generate LICIPD_DATA and LICIPD_META xlsx files + ZIP
"""

import sys
import logging

import orchestrator


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    _setup_logging()
    logger = logging.getLogger('main')
    logger.info("LICIPD pipeline starting")

    result = orchestrator.main()

    quarters = result.get('quarters', [])
    if result.get('skipped'):
        status = 'NO NEW DATA'
    elif result['success']:
        status = 'SUCCESS'
    else:
        status = 'FAILED'

    print("\n" + "=" * 60)
    print("LICIPD PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Status    : {status}")
    if len(quarters) > 1:
        print(f"  Quarters  : {', '.join(quarters)}  ({len(quarters)} processed)")
    elif quarters:
        print(f"  Quarter   : {quarters[0]}")
    else:
        print(f"  Quarter   : {result.get('quarter', 'N/A')}")
    if not result.get('skipped'):
        print(f"  Appended  : {result.get('appended', False)}")
        print(f"  ZIP       : {result.get('zip')}")
    if result.get('errors'):
        print(f"  Warnings  :")
        for e in result['errors']:
            print(f"    - {e}")
    print("=" * 60)

    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
