"""
Test script for Balance Sheet (L-3A / L-3) PDF extraction using PyMuPDF (fitz).
Extracts: Shareholders, Policyholders, Asset Held to Cover Linked Liabilities
from the latest date column.
"""
import sys
import os
import re
import io
import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

def _ensure_utf8_stdout():
    """Force UTF-8 output on Windows (call once in __main__)."""
    if sys.platform == 'win32' and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    elif sys.platform == 'win32':
        try:
            if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass


MONTH_NAME_MAP = {
    'january': 1, 'jan': 1, 'jan.': 1,
    'february': 2, 'feb': 2, 'feb.': 2,
    'march': 3, 'mar': 3, 'mar.': 3,
    'april': 4, 'apr': 4, 'apr.': 4,
    'may': 5,
    'june': 6, 'jun': 6, 'jun.': 6,
    'july': 7, 'jul': 7, 'jul.': 7,
    'august': 8, 'aug': 8, 'aug.': 8,
    'september': 9, 'sept': 9, 'sept.': 9, 'sep': 9, 'sep.': 9,
    'october': 10, 'oct': 10, 'oct.': 10,
    'november': 11, 'nov': 11, 'nov.': 11,
    'december': 12, 'dec': 12, 'dec.': 12,
    # Hindi month names
    '\u091c\u0928\u0935\u0930\u0940': 1,     # जनवरी
    '\u092b\u093c\u0930\u0935\u0930\u0940': 2, # फ़रवरी
    '\u092b\u0930\u0935\u0930\u0940': 2,       # फरवरी
    '\u092e\u093e\u0930\u094d\u091a': 3,       # मार्च
    '\u0905\u092a\u094d\u0930\u0948\u0932': 4, # अप्रैल
    '\u092e\u0908': 5,                         # मई
    '\u091c\u0942\u0928': 6,                   # जून
    '\u091c\u0941\u0932\u093e\u0908': 7,       # जुलाई
    '\u0905\u0917\u0938\u094d\u0924': 8,       # अगस्त
    '\u0938\u093f\u0924\u0902\u092c\u0930': 9, # सितंबर
    '\u0905\u0915\u094d\u0924\u0942\u092c\u0930': 10, # अक्तूबर
    '\u0928\u0935\u0902\u092c\u0930': 11,      # नवंबर
    '\u0926\u093f\u0938\u0902\u092c\u0930': 12, # दिसंबर
}

# Schedule Reference -> Column Code mapping (most reliable for Balance Sheet)
SCHEDULE_REF_MAP = {
    'L-12': 'LICIPD.BALANCESHEET.SHAREHOLDERS.Q',
    'L-13': 'LICIPD.BALANCESHEET.POLICYHOLDERS.Q',
    'L-14': 'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
}


def parse_value(text):
    """Parse a numeric value from PDF text. Handles Indian formatting, parentheses, NIL, dash."""
    if not text or not text.strip():
        return 'NA'
    text = text.strip()
    if text.upper() == 'NIL':
        return 'NA'
    if text in ['-', '\u2013', '\u2014', '']:
        return 'NA'
    is_negative = False
    if text.startswith('(') and text.endswith(')'):
        is_negative = True
        text = text[1:-1].strip()
    text = text.replace(',', '')
    try:
        val = float(text)
        if is_negative:
            val = -val
        return val
    except ValueError:
        return 'NA'


def parse_date_from_text(text):
    """Parse date from header text. Returns (day, month, year) or None.
    Handles: 'As at March 31, 2026', 'As at Sept. 30, 2025', 'As at 31.12.2025'
    """
    if not text:
        return None
    text = text.replace('\n', ' ').strip()

    # Try DD.MM.YYYY or DD/MM/YYYY
    m = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    # Try "Month DD, YYYY" or "Month. DD, YYYY" (handles abbreviated months)
    m = re.search(r'(\w+\.?)\s+(\d{1,2}),?\s*(\d{4})', text)
    if m:
        month_str = m.group(1).lower()
        month = MONTH_NAME_MAP.get(month_str, 0)
        if month > 0:
            return int(m.group(2)), month, int(m.group(3))

    # Try Hindi format: "DD [Hindi month], YYYY" (e.g., "30 जून, 2025 तक")
    m = re.search(r'(\d{1,2})\s+(\S+),?\s*(\d{4})', text)
    if m:
        day = int(m.group(1))
        month_str = m.group(2).strip().rstrip(',')
        year = int(m.group(3))
        month = MONTH_NAME_MAP.get(month_str, 0)
        if month > 0:
            return day, month, year

    return None


def detect_date_columns(rows):
    """Find date columns in table header rows. Returns list of (col_index, date_text, date_value)."""
    date_cols = []
    for i, row in enumerate(rows[:5]):  # Only check first 5 rows for headers
        for j, cell in enumerate(row):
            if not cell:
                continue
            cell_clean = cell.replace('\n', ' ').strip()
            # Look for "As at" or "As on" prefix with a date (English)
            if re.search(r'as\s+(at|on)\s+', cell_clean, re.IGNORECASE):
                parsed = parse_date_from_text(cell_clean)
                if parsed:
                    day, month, year = parsed
                    date_val = year * 10000 + month * 100 + day
                    date_cols.append((j, cell_clean, date_val))
            # Hindi date format: "30 जून, 2025 तक" (DD [Hindi month], YYYY तक)
            elif '\u0924\u0915' in cell_clean or re.search(r'\d{1,2}\s+\S+,?\s*\d{4}', cell_clean):
                parsed = parse_date_from_text(cell_clean)
                if parsed:
                    day, month, year = parsed
                    date_val = year * 10000 + month * 100 + day
                    date_cols.append((j, cell_clean, date_val))
    return date_cols


def extract_balance_sheet(pdf_path):
    """Extract Balance Sheet values from PDF using fitz."""
    print(f"\n{'='*70}")
    print(f"Extracting Balance Sheet from: {os.path.basename(pdf_path)}")
    print(f"{'='*70}")

    doc = fitz.open(pdf_path)
    page = doc[0]

    tables = page.find_tables()
    print(f"Tables found on page 1: {len(tables.tables)}")

    results = {}
    date_detected = None

    if not tables.tables:
        print("ERROR: No tables found on page 1!")
        doc.close()
        return results, date_detected

    best_table = max(tables.tables, key=lambda t: len(t.extract()))
    rows = best_table.extract()
    print(f"Best table: {len(rows)} rows x {len(rows[0]) if rows else 0} cols")

    # Detect date columns
    date_cols = detect_date_columns(rows)
    print(f"Date columns detected: {[(c[0], c[1]) for c in date_cols]}")

    if not date_cols:
        print("ERROR: No date columns detected!")
        doc.close()
        return results, date_detected

    # Pick latest date column
    latest = max(date_cols, key=lambda x: x[2])
    latest_col_idx = latest[0]
    date_detected = latest[1]
    print(f"Using latest: col={latest_col_idx}, date='{date_detected}'")

    # Find APPLICATION OF FUNDS section start
    app_of_funds_row = None
    for i, row in enumerate(rows):
        for cell in row:
            if cell and 'application of funds' in cell.lower():
                app_of_funds_row = i
                break
        if app_of_funds_row is not None:
            break

    search_start = app_of_funds_row if app_of_funds_row is not None else 0
    print(f"APPLICATION OF FUNDS starts at row {search_start}")

    # Primary method: Match by Schedule Reference (L-12, L-13, L-14)
    # The Schedule Ref column is typically column index 2
    schedule_col = None
    for j, cell in enumerate(rows[0]):
        if cell and ('schedule' in cell.lower() or '\u0905\u0928\u0941\u0938\u0942\u091a\u0940' in cell):
            # 'schedule' or Hindi 'अनुसूची' (schedule)
            schedule_col = j
            break

    if schedule_col is not None:
        print(f"Schedule reference column: {schedule_col}")
        for i, row in enumerate(rows):
            if i <= search_start:
                continue
            if schedule_col < len(row) and row[schedule_col]:
                ref = row[schedule_col].strip()
                # Normalize Hindi "एल" to "L" for matching
                ref_normalized = ref.replace('\u090f\u0932', 'L').replace('\u2013', '-')
                # Also normalize spacing: "L 12" -> "L-12"
                ref_normalized = re.sub(r'L\s+(\d+)', r'L-\1', ref_normalized)
                for sched_ref, code in SCHEDULE_REF_MAP.items():
                    if sched_ref in ref or sched_ref in ref_normalized:
                        val_text = row[latest_col_idx] if latest_col_idx < len(row) else None
                        val = parse_value(val_text)
                        results[code] = val
                        label = row[1].strip() if len(row) > 1 and row[1] else '?'
                        print(f"  MATCH [{sched_ref}]: '{label}' = {val}")
                        break

    # Fallback: text-based label matching in APPLICATION OF FUNDS section
    if len(results) < 3:
        print(f"\nSchedule ref got {len(results)}/3, trying label fallback...")
        for i, row in enumerate(rows):
            if i <= search_start:
                continue
            label_cell = None
            for cell in row:
                if cell and cell.strip():
                    label_cell = cell.strip()
                    break
            if not label_cell:
                continue

            label_lower = label_cell.lower().strip()
            # Clean up: remove unicode chars, trailing colons, leading numbers
            label_lower = re.sub(r'[^\x00-\x7f]', '', label_lower).strip()
            label_lower = re.sub(r'^\d+\.?\s*', '', label_lower).strip()
            label_lower = label_lower.rstrip(':').strip()

            for pattern, code in config.BALANCE_SHEET_LABELS.items():
                if code not in results and pattern in label_lower:
                    val_text = row[latest_col_idx] if latest_col_idx < len(row) else None
                    val = parse_value(val_text)
                    if val != 'NA':  # Only accept if we got a real value
                        results[code] = val
                        print(f"  LABEL MATCH: '{label_cell}' -> {code} = {val}")
                    break

    doc.close()

    print(f"\n--- RESULTS ---")
    expected_codes = [
        'LICIPD.BALANCESHEET.SHAREHOLDERS.Q',
        'LICIPD.BALANCESHEET.POLICYHOLDERS.Q',
        'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
    ]
    for code in expected_codes:
        val = results.get(code, 'MISSING')
        print(f"  {code}: {val}")

    return results, date_detected


def date_to_quarter(date_text):
    """Convert date text to quarter label. E.g. 'As at March 31, 2026' -> '2026-Q1'"""
    if not date_text:
        return None
    parsed = parse_date_from_text(date_text)
    if not parsed:
        return None
    _, month, year = parsed
    quarter = config.MONTH_TO_QUARTER.get(month)
    if quarter:
        return f"{year}-{quarter}"
    return None


# Known expected values from the master CSV for verification
EXPECTED_VALUES = {
    '2026-Q1': {
        'LICIPD.BALANCESHEET.SHAREHOLDERS.Q': 150740.33,
        'LICIPD.BALANCESHEET.POLICYHOLDERS.Q': 5333262.11,
        'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q': 61896.94,
    },
    '2025-Q4': {
        'LICIPD.BALANCESHEET.SHAREHOLDERS.Q': 137912.58,
        'LICIPD.BALANCESHEET.POLICYHOLDERS.Q': 5528395.36,
        'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q': 63526.63,
    },
    '2025-Q3': {
        'LICIPD.BALANCESHEET.SHAREHOLDERS.Q': 128470.47,
        'LICIPD.BALANCESHEET.POLICYHOLDERS.Q': 5354740.62,
        'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q': 56977.43,
    },
    '2025-Q2': {
        'LICIPD.BALANCESHEET.SHAREHOLDERS.Q': 123558.5,
        'LICIPD.BALANCESHEET.POLICYHOLDERS.Q': 5354407.93,
        'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q': 53722.73,
    },
}


if __name__ == '__main__':
    _ensure_utf8_stdout()
    test_pdfs = []

    march_pdf = os.path.join(config.BASE_DIR, 'Project_information',
                             'L-3A- Balance Sheet as on 31.03.2026.pdf')
    if os.path.exists(march_pdf):
        test_pdfs.append(('March 2026', march_pdf))

    dec_pdf = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                           'As at December 31, 2025',
                           'L-3A- Balance Sheet as at 31.12.2025.pdf')
    if os.path.exists(dec_pdf):
        test_pdfs.append(('December 2025', dec_pdf))

    sep_pdf = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                           'As at September 30, 2025',
                           'L-3- Balance Sheet as at 30.09.2025.pdf')
    if os.path.exists(sep_pdf):
        test_pdfs.append(('September 2025', sep_pdf))

    jun_pdf = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                           'As at June 30, 2025',
                           'L-3-Balance Sheet as at 30.06.2025.pdf')
    if os.path.exists(jun_pdf):
        test_pdfs.append(('June 2025', jun_pdf))

    if not test_pdfs:
        print("No test PDFs found!")
        sys.exit(1)

    print(f"Found {len(test_pdfs)} test PDFs")

    all_pass = True
    for label, pdf_path in test_pdfs:
        print(f"\n{'#'*70}")
        print(f"# Testing: {label}")
        print(f"{'#'*70}")
        results, date_text = extract_balance_sheet(pdf_path)
        quarter = date_to_quarter(date_text)
        print(f"\nQuarter label: {quarter}")

        if len(results) < 3:
            print(f"FAIL: Only extracted {len(results)}/3 fields!")
            all_pass = False
        else:
            # Verify against known values if available
            if quarter and quarter in EXPECTED_VALUES:
                expected = EXPECTED_VALUES[quarter]
                match = True
                for code, exp_val in expected.items():
                    got = results.get(code, 'MISSING')
                    if isinstance(got, float) and abs(got - exp_val) < 0.01:
                        print(f"  VERIFY OK: {code} = {got} (expected {exp_val})")
                    else:
                        print(f"  VERIFY FAIL: {code} = {got} (expected {exp_val})")
                        match = False
                if not match:
                    all_pass = False
            else:
                print(f"  OK: All 3 fields extracted (no expected values to verify)")

    print(f"\n{'='*70}")
    print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print(f"{'='*70}")
