"""
Test script for Investments Policyholders (L-13) PDF extraction using PyMuPDF (fitz).
Extracts up to 28 fields: 17 LONG TERM + 11 SHORT TERM from the latest date column.

Multi-strategy label-context-aware extraction (bilingual English/Hindi):
  Strategy 1: English label text matching against config.INVPHS_LABELS
  Strategy 2: IRDA sub-item prefix matching (aa=Equity, b=MF, d=Debentures, etc.)
  Strategy 3: Row number context matching (1=GovtSecs, 2=OthApproved, etc.)
  Strategy 4: Hindi keyword fragment matching for Hindi PDFs

All strategies work together - label context is ALWAYS the primary signal,
structural markers (prefixes, row numbers) serve as reinforcement and fallback.
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
    date_to_quarter, MONTH_NAME_MAP, _ensure_utf8_stdout,
)

# ── Sub-item prefix -> field suffix (IRDA Form L-13 standard) ────────────────
# These identifiers are defined by Indian insurance regulation and appear
# identically in BOTH English and Hindi PDFs. They are semantic identifiers,
# not positional assumptions.
SUBITEM_TO_FIELD = {
    'aa': 'EQUITY',
    'bb': 'PREFERENCE',
    'b':  'MUTUALFUND',
    'd':  'DEBENTBOND',
    'e':  'OTHSECSBOND',
    'i':  'OTHSECSBOND',   # Alternate sub-item label used in some PDFs
    'f':  'SUBSIDIARIES',
    'g':  'REALESTATE',
}

# ── Row number -> field suffix (IRDA form numbering) ─────────────────────────
# Main numbered items in the L-13 form. Row number 3 is always the "Shares"
# sub-header so it's intentionally excluded.
ROWNUM_TO_FIELD = {
    '1': 'GOVTSECS',
    '2': 'OTHAPPRSECS',
    '4': 'INFRASOCIALSECTOR',
    '5': 'OTHERNONAPPROVED',
    '6': 'PROVISIONDOUBTFUL',
}

# ── Section detection markers (bilingual) ────────────────────────────────────
SECTION_MARKERS = {
    'long_term': [
        'long term', 'long-term',
        '\u0932\u0902\u092c\u0940 \u0905\u0935\u093f\u0927',     # लंबी अविध
        '\u0932\u0902\u092c\u0940 \u0905\u0935\u0927\u093f',     # लंबी अवधि
        '\u0926\u0940\u0930\u094d\u0918\u0915\u093e\u0932\u093f\u0915',  # दीर्घकालिक
    ],
    'short_term': [
        'short term', 'short-term',
        '\u0932\u0918\u0941 \u0905\u0935\u093f\u0927',           # लघु अविध
        '\u0932\u0918\u0941 \u0905\u0935\u0927\u093f',           # लघु अवधि
        '\u0905\u0932\u094d\u092a\u0915\u093e\u0932\u093f\u0915',       # अल्पकालिक
    ],
}

# ── Total row markers (bilingual) ────────────────────────────────────────────
TOTAL_MARKERS = ['total', '\u0915\u0941\u0932', '\u092f\u094b\u0917']  # total, कुल, योग

# ── Hindi keyword fragments for label classification ──────────────────────────
# Maps field suffix to Hindi keyword fragments that survive PDF text extraction.
# Used when English label matching fails (Hindi PDFs have encoding artifacts
# but certain character sequences reliably survive).
HINDI_FIELD_KEYWORDS = {
    'GOVTSECS':          ['\u0938\u0930\u0915\u093e\u0930\u0940'],                    # सरकारी
    'OTHAPPRSECS':       ['\u02e2\u0940\u0915\u0943 \u0924 \u016e\u093f\u0924\u092d\u0942\u093f\u0924\u092f\u093e\u0902'],  # specific fragment for "approved securities"
    'EQUITY':            ['\u0907\u093f\u01a3\u091f\u0940', '\u0907\u0915\u094d\u0935\u093f\u091f\u0940'],  # इिƓटी, इक्विटी
    'PREFERENCE':        ['\u0935\u0930\u0940\u092f\u0924\u093e'],                    # वरीयता
    'MUTUALFUND':        ['\u0284\u0942\u091a\u0941\u0905\u0932', '\u092e\u094d\u092f\u0942\u091a\u0941\u0905\u0932'],  # ʄूचुअल, म्यूचुअल
    'DEBENTBOND':        ['\u093f\u0921\u092c\u0150\u091a\u0930', '\u0921\u093f\u092c\u0947\u0902\u091a\u0930'],  # िडबŐचर, डिबेंचर
    'OTHSECSBOND':       ['\u092c\u0949\u0235\u094d\u0938', '\u092c\u0949\u0928\u094d\u0921'],  # बॉȵ्स, बॉन्ड
    'SUBSIDIARIES':      ['\u0938\u0939\u093e\u092f\u0915'],                          # सहायक
    'REALESTATE':        ['\u090f\u02d0\u0947\u091f', '\u0930\u093f\u092f\u0932', '\u0938\u0902\u092a\u093f\u0245'],  # एːेट, रियल, संपिȅ
    'INFRASOCIALSECTOR': ['\u092c\u0941\u093f\u0928\u092f\u093e\u0926\u0940', '\u0922\u093e\u0902\u091a\u0947'],  # बुिनयादी, ढांचे
    'OTHERNONAPPROVED':  ['\u0905\u0932\u093e\u0935\u093e'],                          # अलावा
    'PROVISIONDOUBTFUL': ['\u016e\u093e\u0935\u0927\u093e\u0928', '\u0938\u0902\u093f\u0926'],  # Ůावधान, संिद
}


def clean_label(text):
    """Clean a PDF row label for matching.

    Strips leading row numbers, sub-item prefixes like (aa)/(b), trailing
    colons/dashes, and collapses whitespace. Returns lowercased text.
    """
    if not text:
        return ''
    t = text.strip().replace('\n', ' ')
    t = re.sub(r'^\d+\.?\s*', '', t).strip()
    t = re.sub(r'^\([a-z]+\)\s*', '', t).strip()
    t = re.sub(r'[:\u2013\u2014\-]+$', '', t).strip()
    t = re.sub(r'\s+', ' ', t)
    return t.lower()


def find_label_column(rows):
    """Dynamically detect which column contains row labels (Particulars).

    Checks header rows for 'Particulars' (English) or 'िववरण' (Hindi).
    Falls back to scoring columns by non-numeric text content.
    """
    for i, row in enumerate(rows[:5]):
        for j, cell in enumerate(row):
            if not cell:
                continue
            cell_text = cell.lower().replace('\n', ' ')
            if 'particulars' in cell_text or '\u093f\u0935\u0935\u0930\u0923' in cell:
                return j
    # Fallback: column with the most non-numeric text cells
    if not rows:
        return 1
    num_cols = len(rows[0])
    text_scores = [0] * num_cols
    for row in rows[3:]:
        for j, cell in enumerate(row):
            if j >= num_cols:
                break
            if cell and cell.strip() and not re.match(r'^[\d,.()\-\u2013\s]*$', cell.strip()):
                text_scores[j] += 1
    if any(text_scores):
        return max(range(num_cols), key=lambda j: text_scores[j])
    return 1


def detect_section_change(row):
    """Check if any cell in the row signals a section change.

    Returns 'long_term', 'short_term', or None.
    Scans ALL cells in the row so section markers are found regardless
    of which column they appear in.
    """
    all_text = ' '.join(
        (c or '').replace('\n', ' ').strip().lower() for c in row
    )
    for section, markers in SECTION_MARKERS.items():
        for marker in markers:
            if marker in all_text:
                return section
    return None


def is_total_row(label_text):
    """Check if a label represents the TOTAL row (English or Hindi)."""
    if not label_text:
        return False
    cleaned = label_text.strip().lower()
    return cleaned in TOTAL_MARKERS


def extract_subitem_prefix(text):
    """Extract IRDA sub-item prefix from label text.

    E.g., '(aa) Equity' -> 'aa', '(b) Mutual Funds' -> 'b'.
    Returns None if no sub-item prefix found.
    """
    if not text:
        return None
    m = re.match(r'^\s*\(([a-z]+)\)', text.strip())
    return m.group(1) if m else None


def match_hindi_keywords(label_text, section):
    """Classify a Hindi label using keyword fragment matching.

    Returns column code or None. Handles disambiguation:
    - 'अलावा' (other than/except) disambiguates OTHERNONAPPROVED from OTHAPPRSECS
    - Requires 'सहायक' for SUBSIDIARIES to avoid false matches
    """
    if not label_text:
        return None
    section_upper = 'LONGTERM' if section == 'long_term' else 'SHORTTERM'

    for field_suffix, keywords in HINDI_FIELD_KEYWORDS.items():
        for kw in keywords:
            if kw in label_text:
                # Disambiguation: 'अलावा' present means OTHERNONAPPROVED, not OTHAPPRSECS
                if field_suffix == 'OTHAPPRSECS' and '\u0905\u0932\u093e\u0935\u093e' in label_text:
                    continue
                code = f'LICIPD.INVPHS.{section_upper}.{field_suffix}.Q'
                if code in config.COLUMN_CODES:
                    return code
    return None


def extract_investments_ph(pdf_path):
    """Extract Investments Policyholders values from L-13 PDF.

    Uses four matching strategies in priority order:
      1. English label text matching against config.INVPHS_LABELS
      2. IRDA sub-item prefix matching (language-agnostic regulatory identifiers)
      3. Row number context matching (language-agnostic regulatory numbering)
      4. Hindi keyword fragment matching

    The first strategy that returns a valid code is used. If a code was
    previously stored with NA and a new match provides a real value, the
    real value overrides (handles (e) header vs value row pattern).
    """
    print(f"\n{'='*70}")
    print(f"Extracting L-13 from: {os.path.basename(pdf_path)}")
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

    # Detect date columns dynamically
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

    # Dynamically detect label column
    label_col = find_label_column(rows)
    print(f"Label column: {label_col}")

    results = {}
    section = None  # 'long_term' or 'short_term'

    for i, row in enumerate(rows):
        # --- Section detection (bilingual, scans all cells) ---
        new_section = detect_section_change(row)
        if new_section:
            section = new_section
            print(f"  [Section: {section.upper().replace('_', ' ')}] row {i}")
            continue

        if section is None:
            continue

        # Get raw label from dynamically detected label column
        raw_label = row[label_col].strip() if label_col < len(row) and row[label_col] else ''
        if not raw_label:
            continue

        # Get row number from column 0 (may differ from label_col)
        col0 = row[0].strip() if row[0] else ''
        row_num_text = col0 if re.match(r'^\d$', col0) else ''

        # Get value from latest date column
        val_text = row[latest_col] if latest_col < len(row) else None
        val = parse_value(val_text)

        # --- TOTAL detection (bilingual) ---
        if is_total_row(raw_label):
            # Grand TOTAL always comes after SHORT TERM section -> maps to SHORTTERM.TOTAL
            code = 'LICIPD.INVPHS.SHORTTERM.TOTAL.Q'
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                print(f"  [TOTAL] TOTAL = {val}")
            continue

        # Skip known sub-headers: (a) Shares, (c) Derivative Instruments
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
            s1_code = config.INVPHS_LABELS.get(key)
            if s1_code is None:
                # Partial matching: config label contained in cleaned, or vice versa
                for config_key, config_code in config.INVPHS_LABELS.items():
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
            s2_code = f'LICIPD.INVPHS.{section_upper}.{field_suffix}.Q'
            if s2_code in config.COLUMN_CODES:
                if code is None:
                    code = s2_code
                    match_strategy = 'PREFIX'
                # If Strategy 1 already matched, keep it (label context is king)

        # ── Strategy 3: Row number matching ─────────────────────────────
        if not code and row_num_text and row_num_text in ROWNUM_TO_FIELD:
            field_suffix = ROWNUM_TO_FIELD[row_num_text]
            s3_code = f'LICIPD.INVPHS.{section_upper}.{field_suffix}.Q'
            if s3_code in config.COLUMN_CODES:
                code = s3_code
                match_strategy = 'ROWNUM'

        # ── Strategy 4: Hindi keyword matching ──────────────────────────
        if not code:
            s4_code = match_hindi_keywords(raw_label, section)
            if s4_code:
                code = s4_code
                match_strategy = 'HINDI'

        # ── Special case: unlabeled "Other Securities & Bonds" row ──────
        # In some English PDFs, (e) is a header with empty value, and the
        # actual OTHSECSBOND value is in the NEXT row with no prefix/number.
        if not code and not prefix and not row_num_text:
            if cleaned and 'other securities' in cleaned:
                code = f'LICIPD.INVPHS.{section_upper}.OTHSECSBOND.Q'
                match_strategy = 'SPECIAL'

        # Store result (override NA with real values)
        if code:
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                short_name = code.split('.')[-2]
                print(f"  [{match_strategy}] {short_name} = {val}")

    doc.close()

    # Print summary
    print(f"\n--- RESULTS ({len(results)} fields) ---")
    expected_lt = [c for c in config.COLUMN_CODES if 'INVPHS.LONGTERM' in c]
    expected_st = [c for c in config.COLUMN_CODES if 'INVPHS.SHORTTERM' in c]

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
        'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q': 3198707.72,
        'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q': 37.61,
        'LICIPD.INVPHS.LONGTERM.EQUITY.Q': 1268775.38,
        'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q': 23519.79,
        'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q': 139139.77,
        'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q': 151.92,
        'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q': 33072.22,
        'LICIPD.INVPHS.LONGTERM.REALESTATE.Q': 23978.78,
        'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q': 426872.80,
        'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q': 39573.70,
        'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q': -5497.48,
        'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q': 144151.15,
        'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q': 3994.48,
        'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q': 21476.80,
        'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q': 4594.0,
        'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q': 10310.30,
        'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q': 2542.49,
        'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q': -2139.32,
        'LICIPD.INVPHS.SHORTTERM.TOTAL.Q': 5333262.11,
    },
    '2025-Q4': {
        'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q': 3205021.18,
        'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q': 3832.72,
        'LICIPD.INVPHS.LONGTERM.EQUITY.Q': 1473312.61,
        'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q': 25862.3,
        'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q': 132561.61,
        'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q': 162.13,
        'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q': 33072.22,
        'LICIPD.INVPHS.LONGTERM.REALESTATE.Q': 17203.58,
        'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q': 438667.11,
        'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q': 44858.97,
        'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q': -5425.54,
        'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q': 119846.24,
        'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q': 2714.95,
        'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q': 21704.34,
        'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q': 4150.0,
        'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q': 9913.39,
        'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q': 3080.53,
        'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q': -2142.98,
        'LICIPD.INVPHS.SHORTTERM.TOTAL.Q': 5528395.36,
    },
    '2025-Q3': {
        'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q': 3144978.61,
        'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q': 3832.26,
        'LICIPD.INVPHS.LONGTERM.EQUITY.Q': 1367214.89,
        'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q': 25018.96,
        'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q': 133480.1,
        'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q': 160.73,
        'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q': 33072.22,
        'LICIPD.INVPHS.LONGTERM.REALESTATE.Q': 17170.0,
        'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q': 437489.36,
        'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q': 41849.74,
        'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q': -5427.42,
        'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q': 125635.68,
        'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q': 2715.36,
        'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q': 16232.72,
        'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q': 2125.0,
        'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q': 8073.91,
        'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q': 3427.42,
        'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q': -2308.92,
        'LICIPD.INVPHS.SHORTTERM.TOTAL.Q': 5354740.62,
    },
    '2025-Q2': {
        'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q': 3110445.47,
        'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q': 3816.44,
        'LICIPD.INVPHS.LONGTERM.EQUITY.Q': 1419261.97,
        'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q': 24940.01,
        'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q': 132871.49,
        'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q': 167.87,
        'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q': 33072.22,
        'LICIPD.INVPHS.LONGTERM.REALESTATE.Q': 17162.09,
        'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q': 443188.33,
        'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q': 43043.19,
        'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q': -5658.88,
        'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q': 106561.38,
        'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q': 2715.76,
        'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q': 13054.41,
        'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q': 1925.0,
        'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q': 6716.45,
        'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q': 3436.3,
        'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q': -2311.57,
        'LICIPD.INVPHS.SHORTTERM.TOTAL.Q': 5354407.93,
    },
}


if __name__ == '__main__':
    test_pdfs = []

    march = os.path.join(config.BASE_DIR, 'Project_information',
                         'L-13- Investments - Policyholders as on 31.03.2026.pdf')
    if os.path.exists(march):
        test_pdfs.append(('March 2026', march))

    dec = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at December 31, 2025',
                       'L-13- Investments Policyholders as at 31.12.2025.pdf')
    if os.path.exists(dec):
        test_pdfs.append(('December 2025', dec))

    sep = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at September 30, 2025',
                       'L-13- Investments PHs as at 30.09.2025.pdf')
    if os.path.exists(sep):
        test_pdfs.append(('September 2025', sep))

    jun = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdfs',
                       'As at June 30, 2025',
                       'L-13-Investments PHs as at 30.06.2025.pdf')
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
        results, date_text = extract_investments_ph(pdf_path)
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
            if len(results) < 15:
                print(f"  WARNING: Only {len(results)} fields extracted")
                all_pass = False

    print(f"\n{'='*70}")
    print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print(f"{'='*70}")
