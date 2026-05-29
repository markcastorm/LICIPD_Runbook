"""
Test script for Investments Linked Business (L-14) PDF extraction using PyMuPDF (fitz).
Extracts up to 18 fields: 9 LONG TERM + 9 SHORT TERM from the latest date column.

Uses the same multi-strategy label-context-aware extraction as L-13:
  Strategy 1: English label text matching against config.INVLINKED_LABELS
  Strategy 2: IRDA sub-item prefix matching (aa=Equity, b=MF, d=Debentures, etc.)
  Strategy 3: Row number context matching (1=GovtSecs, 2=OthApproved, etc.)
  Strategy 4: Hindi keyword fragment matching

Key differences from L-13 (Policyholders):
  - Row 6 maps to NETCURRASST (Other Current Assets), not PROVISIONDOUBTFUL
  - (e) Other Securities IS the value row (no sub-row pattern)
  - Fewer mapped fields (no SUBSIDIARIES/REALESTATE/PROVISIONDOUBTFUL in LT,
    no EQUITY/PREFERENCE in ST)
  - Code validates against COLUMN_CODES so unmapped prefixes are skipped
"""
import sys
import os
import re
import io
import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from test_balance_sheet import (
    parse_value, parse_date_from_text, detect_date_columns,
    date_to_quarter, _ensure_utf8_stdout,
)
from test_investments_ph import (
    clean_label, find_label_column, detect_section_change,
    is_total_row, extract_subitem_prefix, match_hindi_keywords,
    SUBITEM_TO_FIELD, HINDI_FIELD_KEYWORDS,
)

# ── L-14 specific row number mapping ─────────────────────────────────────────
# Same as L-13 except row 6 = NETCURRASST (not PROVISIONDOUBTFUL)
ROWNUM_TO_FIELD_L14 = {
    '1': 'GOVTSECS',
    '2': 'OTHAPPRSECS',
    '4': 'INFRASOCIALSECTOR',
    '5': 'OTHERNONAPPROVED',
    '6': 'NETCURRASST',
}

CODE_PREFIX = 'LICIPD.INVLINKED'


def match_hindi_keywords_linked(label_text, section):
    """Hindi keyword matching adapted for INVLINKED column codes.

    Builds INVLINKED codes and validates against COLUMN_CODES.
    """
    if not label_text:
        return None
    section_upper = 'LONGTERM' if section == 'long_term' else 'SHORTTERM'

    for field_suffix, keywords in HINDI_FIELD_KEYWORDS.items():
        for kw in keywords:
            if kw in label_text:
                if field_suffix == 'OTHAPPRSECS' and '\u0905\u0932\u093e\u0935\u093e' in label_text:
                    continue
                code = f'{CODE_PREFIX}.{section_upper}.{field_suffix}.Q'
                if code in config.COLUMN_CODES:
                    return code
    return None


def extract_investments_linked(pdf_path):
    """Extract Investments Linked Business values from L-14 PDF.

    Uses four matching strategies (same as L-13):
      1. English label text matching against config.INVLINKED_LABELS
      2. IRDA sub-item prefix matching
      3. Row number context matching (row 6 = NETCURRASST for L-14)
      4. Hindi keyword fragment matching

    All generated codes are validated against config.COLUMN_CODES.
    """
    print(f"\n{'='*70}")
    print(f"Extracting L-14 from: {os.path.basename(pdf_path)}")
    print(f"{'='*70}")

    doc = fitz.open(pdf_path)
    page = doc[0]
    tables = page.find_tables()

    if not tables.tables:
        print("ERROR: No tables found!")
        doc.close()
        return {}, None

    best_table = max(tables.tables, key=lambda t: len(t.extract()))
    rows = best_table.extract()
    num_cols = len(rows[0]) if rows else 0
    print(f"Table: {len(rows)} rows x {num_cols} cols")

    date_cols = detect_date_columns(rows)
    print(f"Date columns: {[(c[0], c[1]) for c in date_cols]}")

    if not date_cols:
        print("ERROR: No date columns detected!")
        doc.close()
        return {}, None

    latest = max(date_cols, key=lambda x: x[2])
    latest_col = latest[0]
    date_detected = latest[1]
    print(f"Using latest: col={latest_col}, date='{date_detected}'")

    label_col = find_label_column(rows)
    print(f"Label column: {label_col}")

    results = {}
    section = None

    for i, row in enumerate(rows):
        new_section = detect_section_change(row)
        if new_section:
            section = new_section
            print(f"  [Section: {section.upper().replace('_', ' ')}] row {i}")
            continue

        if section is None:
            continue

        raw_label = row[label_col].strip() if label_col < len(row) and row[label_col] else ''
        if not raw_label:
            continue

        col0 = row[0].strip() if row[0] else ''
        row_num_text = col0 if re.match(r'^\d$', col0) else ''

        val_text = row[latest_col] if latest_col < len(row) else None
        val = parse_value(val_text)

        # TOTAL detection
        if is_total_row(raw_label):
            code = f'{CODE_PREFIX}.SHORTTERM.TOTAL.Q'
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                print(f"  [TOTAL] TOTAL = {val}")
            continue

        # Skip sub-headers: (a) Shares, (c)/(c ) Derivative Instruments
        prefix = extract_subitem_prefix(raw_label)
        if prefix in ('a', 'c'):
            continue

        section_upper = 'LONGTERM' if section == 'long_term' else 'SHORTTERM'
        code = None
        match_strategy = None

        # ── Strategy 1: English label text matching ──────────────────────
        cleaned = clean_label(raw_label)
        if cleaned:
            key = (section, cleaned)
            s1_code = config.INVLINKED_LABELS.get(key)
            if s1_code is None:
                for config_key, config_code in config.INVLINKED_LABELS.items():
                    if config_key[0] != section:
                        continue
                    if config_key[1] in cleaned or (cleaned in config_key[1] and len(cleaned) > 3):
                        s1_code = config_code
                        break
            if s1_code:
                code = s1_code
                match_strategy = 'LABEL'

        # ── Strategy 2: Sub-item prefix matching ────────────────────────
        if prefix and prefix in SUBITEM_TO_FIELD:
            field_suffix = SUBITEM_TO_FIELD[prefix]
            s2_code = f'{CODE_PREFIX}.{section_upper}.{field_suffix}.Q'
            if s2_code in config.COLUMN_CODES:
                if code is None:
                    code = s2_code
                    match_strategy = 'PREFIX'

        # ── Strategy 3: Row number matching ─────────────────────────────
        if not code and row_num_text and row_num_text in ROWNUM_TO_FIELD_L14:
            field_suffix = ROWNUM_TO_FIELD_L14[row_num_text]
            s3_code = f'{CODE_PREFIX}.{section_upper}.{field_suffix}.Q'
            if s3_code in config.COLUMN_CODES:
                code = s3_code
                match_strategy = 'ROWNUM'

        # ── Strategy 4: Hindi keyword matching ──────────────────────────
        if not code:
            s4_code = match_hindi_keywords_linked(raw_label, section)
            if s4_code:
                code = s4_code
                match_strategy = 'HINDI'

        # Store result (override NA with real values)
        if code:
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                short_name = code.split('.')[-2]
                print(f"  [{match_strategy}] {short_name} = {val}")

    doc.close()

    # Print summary
    print(f"\n--- RESULTS ({len(results)} fields) ---")
    expected_lt = [c for c in config.COLUMN_CODES if 'INVLINKED.LONGTERM' in c]
    expected_st = [c for c in config.COLUMN_CODES if 'INVLINKED.SHORTTERM' in c]

    print("  LONG TERM:")
    for code in expected_lt:
        val = results.get(code, 'NA')
        short = code.split('.')[-2]
        print(f"    {short}: {val}")

    print("  SHORT TERM:")
    for code in expected_st:
        val = results.get(code, 'NA')
        short = code.split('.')[-2]
        print(f"    {short}: {val}")

    return results, date_detected


# ── Expected values from master CSV for verification ─────────────────────────
EXPECTED_VALUES = {
    '2026-Q1': {
        'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q': 15324.59,
        'LICIPD.INVLINKED.LONGTERM.EQUITY.Q': 37375.37,
        'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q': 278.69,
        'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q': 3647.06,
        'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q': 47.02,
        'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q': 1210.88,
        'LICIPD.INVLINKED.SHORTTERM.OTHAPPRSECS.Q': 0.05,
        'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q': 2175.6,
        'LICIPD.INVLINKED.SHORTTERM.OTHSECSBOND.Q': 150.0,
        'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q': 30.72,
        'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q': 1656.96,
        'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q': 61896.94,
    },
    '2025-Q4': {
        'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q': 15566.37,
        'LICIPD.INVLINKED.LONGTERM.OTHAPPRSECS.Q': 0.05,
        'LICIPD.INVLINKED.LONGTERM.EQUITY.Q': 40707.69,
        'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q': 162.06,
        'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q': 3106.41,
        'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q': 50.31,
        'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q': 1202.51,
        'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q': 1681.69,
        'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q': 31.0,
        'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q': 1018.54,
        'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q': 63526.63,
    },
    '2025-Q3': {
        'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q': 14441.65,
        'LICIPD.INVLINKED.LONGTERM.OTHAPPRSECS.Q': 0.05,
        'LICIPD.INVLINKED.LONGTERM.EQUITY.Q': 36132.6,
        'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q': 86.58,
        'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q': 2491.3,
        'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q': 69.18,
        'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q': 1329.58,
        'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q': 1577.57,
        'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q': 117.44,
        'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q': 731.48,
        'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q': 56977.43,
    },
    '2025-Q2': {
        'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q': 13489.31,
        'LICIPD.INVLINKED.LONGTERM.OTHAPPRSECS.Q': 0.05,
        'LICIPD.INVLINKED.LONGTERM.EQUITY.Q': 34744.76,
        'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q': 10.71,
        'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q': 2177.8,
        'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q': 75.4,
        'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q': 1067.49,
        'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q': 1357.2,
        'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q': 86.49,
        'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q': 713.52,
        'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q': 53722.73,
    },
}


if __name__ == '__main__':
    test_pdfs = []

    march = os.path.join(config.BASE_DIR, 'Project_information',
                         'L-14 - Investments - Linked Business as on 31.03.2026.pdf')
    if os.path.exists(march):
        test_pdfs.append(('March 2026', march))

    dec = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at December 31, 2025',
                       'L-14- Assets held to cover linked liabilities as at 31.12.2025.pdf')
    if os.path.exists(dec):
        test_pdfs.append(('December 2025', dec))

    sep = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at September 30, 2025',
                       'L-14- Investments (Linked Busi) as at 30.09.2025.pdf')
    if os.path.exists(sep):
        test_pdfs.append(('September 2025', sep))

    jun = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at June 30, 2025',
                       'L-14- Investments (Linked Busi) as at 30.06.2025.pdf')
    if os.path.exists(jun):
        test_pdfs.append(('June 2025', jun))

    if not test_pdfs:
        print("No test PDFs found!")
        sys.exit(1)

    _ensure_utf8_stdout()
    print(f"Found {len(test_pdfs)} test PDFs")
    all_pass = True

    for label, pdf_path in test_pdfs:
        print(f"\n{'#'*70}")
        print(f"# Testing: {label}")
        print(f"{'#'*70}")
        results, date_text = extract_investments_linked(pdf_path)
        quarter = date_to_quarter(date_text)
        print(f"\nQuarter: {quarter}, Fields extracted: {len(results)}")

        if quarter and quarter in EXPECTED_VALUES:
            expected = EXPECTED_VALUES[quarter]
            for code, exp_val in expected.items():
                got = results.get(code, 'MISSING')
                if isinstance(got, (int, float)) and abs(got - exp_val) < 0.01:
                    pass  # OK
                else:
                    print(f"  VERIFY FAIL: {code.split('.')[-2]} = {got} (expected {exp_val})")
                    all_pass = False
            print(f"  Verified {len(expected)} values against master CSV")
        else:
            if len(results) < 8:
                print(f"  WARNING: Only {len(results)} fields extracted")
                all_pass = False

    print(f"\n{'='*70}")
    print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print(f"{'='*70}")
