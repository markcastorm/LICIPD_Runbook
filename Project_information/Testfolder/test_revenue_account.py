"""
Test script for Revenue Account (L-1A / L-1) PDF extraction using PyMuPDF (fitz).
Extracts 10 fields from the GRAND TOTAL column of the 21-column landscape table.
Handles dual-PDF logic (picks latest by filename date), English and Hindi PDFs.

Fields:
  7 direct:   INTDIVINCOME, INVGAINLOSSREVAL, OTHERINCOME, TOTALINCOME,
              OPERATINGEXP, BENEFITSPAID, BONUSESPAID
  3 calculated:
    PREMIUMSNET     = (a)Premium + (b)ReinsuranceCeded + (c)ReinsuranceAccepted
    INVGAINLOSSSALE = (b)ProfitSale + (c)LossSale  [loss is negative via parentheses]
    NETINCOME       = TOTALINCOME + OPERATINGEXP + BENEFITSPAID + BONUSESPAID

Extraction strategies (applied in order):
  1. Section-aware sub-prefix: (a)/(b)/(c)/(d) within 'premiums' or 'investments' section
  2. Direct label matching: English + Hindi keyword checks
  3. Row-index fallback: for rows where strategies 1 & 2 both fail
"""
import sys
import os
import re
import fitz
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from test_balance_sheet import parse_value, _ensure_utf8_stdout


# ── Section header detection ──────────────────────────────────────────────────
_EN_SECT_PREMIUMS     = 'premiums earned'
_EN_SECT_INVESTMENTS  = 'income from investments'
_EN_SECT_SHAREHOLDERS = "contribution from shareholders"

# Hindi fragments — fitz renders Devanagari in visual byte-order, not logical
# Unicode order.  Use inner substrings that survive both orderings:
#   premiums section header: 'अिजŊत Ůीिमयम - शुȠ' → match on 'ीिमयम'
#   investments section header: 'िनवेशो ंसे आय:' → match on 'वेशो'
#   shareholders: 'शेयरधारको ंके खाते से अंशदान:' → match on 'शेयरधारको'
_HI_SECT_PREMIUMS     = 'ीिमयम'     # inner substr of 'Ůीिमयम' (premium)
_HI_SECT_INVESTMENTS  = 'वेशो'       # inner substr of 'िनवेशो' (investments)
_HI_SECT_SHAREHOLDERS = 'शेयरधारको'  # shareholders

# ── Section → sub-prefix → component/code ────────────────────────────────────
SECTION_PREFIX_MAP = {
    ('premiums',    'a'): '_COMPONENT_PREMIUM',
    ('premiums',    'b'): '_COMPONENT_REINS_CEDED',
    ('premiums',    'c'): '_COMPONENT_REINS_ACCEPTED',
    ('investments', 'a'): 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    ('investments', 'b'): '_COMPONENT_PROFIT_SALE',
    ('investments', 'c'): '_COMPONENT_LOSS_SALE',
    ('investments', 'd'): 'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
    # (e) = Amortisation of Premium/Discount → not in schema, skip
}

# ── Row-index fallback mapping ────────────────────────────────────────────────
# Consistent across all 4 tested quarters (46 rows × 21 cols)
ROW_INDEX_MAP = {
    4:  '_COMPONENT_PREMIUM',
    5:  '_COMPONENT_REINS_CEDED',
    6:  '_COMPONENT_REINS_ACCEPTED',
    8:  'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    9:  '_COMPONENT_PROFIT_SALE',
    10: '_COMPONENT_LOSS_SALE',
    11: 'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
    13: 'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q',
    17: 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
    27: 'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
    28: 'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    29: 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
}

# ── English direct-match patterns ────────────────────────────────────────────
# Matched via substring in lowercased label
_DIRECT_EN = {
    'other income':         'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q',
    'total (a)':            'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
    'total (b)':            'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
    'benefits paid (net)':  'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'benefits paid(net)':   'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'interim bonuses paid': 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
    'bonuses paid':         'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_date_from_filename(pdf_path):
    """Extract datetime from filename pattern DD.MM.YYYY."""
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', os.path.basename(pdf_path))
    if m:
        day, mon, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(yr, mon, day)
    return None


def select_latest_pdf(pdf_paths):
    """Return the PDF with the latest date in its filename."""
    dated = [(p, parse_date_from_filename(p)) for p in pdf_paths if os.path.exists(p)]
    valid = [(p, d) for p, d in dated if d is not None]
    if valid:
        return max(valid, key=lambda x: x[1])[0]
    existing = [p for p in pdf_paths if os.path.exists(p)]
    return existing[0] if existing else None


def quarter_from_pdf_path(pdf_path):
    """Derive YYYY-QN from filename date."""
    d = parse_date_from_filename(pdf_path)
    if d:
        q = config.MONTH_TO_QUARTER.get(d.month)
        if q:
            return f"{d.year}-{q}"
    return None


def find_grand_total_col(rows):
    """Locate GRAND TOTAL column index from header rows."""
    for row in rows[:4]:
        for i, cell in enumerate(row):
            if cell:
                txt = str(cell).strip()
                if 'GRAND TOTAL' in txt.upper() or 'कुल योग' in txt:
                    return i
    return len(rows[0]) - 1 if rows else 0


def get_subitem_prefix(label):
    """Return single-letter prefix for '(a) ...' style labels, else None."""
    m = re.match(r'^\s*\(([a-zA-Z])\)', (label or '').strip())
    return m.group(1).lower() if m else None


def detect_section(label):
    """Return section name if label is a section header, else None.

    Returns 'premiums', 'investments', 'shareholders', or None.
    A row with a sub-item prefix is never a section header.
    """
    if not label or not label.strip():
        return None
    if get_subitem_prefix(label) is not None:
        return None
    lower = label.strip().lower()
    if _EN_SECT_PREMIUMS in lower:
        return 'premiums'
    if _EN_SECT_INVESTMENTS in lower:
        return 'investments'
    if _EN_SECT_SHAREHOLDERS in lower:
        return 'shareholders'
    if _HI_SECT_PREMIUMS in label:
        return 'premiums'
    if _HI_SECT_INVESTMENTS in label:
        return 'investments'
    if _HI_SECT_SHAREHOLDERS in label:
        return 'shareholders'
    return None


def match_direct_label(label):
    """Match a non-sub-item row to a direct code or component key.

    Returns (code_or_component, strategy_tag) or (None, None).
    """
    if not label or get_subitem_prefix(label) is not None:
        return None, None

    lower = label.strip().lower()

    # English substring matches
    for pattern, code in _DIRECT_EN.items():
        if pattern in lower:
            return code, 'LABEL_EN'

    # Hindi: TOTAL (A)/(B) — "कुल (A)"/"कुल (B)" end with "(a)"/"(b)"
    # Safe: sub-items like "(a) Premium" are filtered above; SURPLUS/(DEFICIT)(D)=(A)-(B)-(C)
    # ends with "(c)" not "(a)" or "(b)"
    if lower.strip().endswith('(a)'):
        return 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q', 'LABEL_HI'
    if lower.strip().endswith('(b)'):
        return 'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q', 'LABEL_HI'

    # Hindi Bonuses Paid: contains 'बोनस' — check before Benefits since both have 'भुगतान'
    if 'बोनस' in label:
        return 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q', 'LABEL_HI'

    # Hindi Benefits Paid: 'भुगतान' + 'लाभ'
    if 'भुगतान' in label and 'लाभ' in label:
        return 'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q', 'LABEL_HI'

    # Hindi Other Income: 'आय' (income) — exclude investments header which has 'वेश'
    if 'आय' in label and 'वेश' not in label:
        return 'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q', 'LABEL_HI'

    return None, None


def apply_calculations(components, results):
    """Compute PREMIUMSNET, INVGAINLOSSSALE, NETINCOME."""
    def to_num(v, default=0.0):
        return v if isinstance(v, (int, float)) else default

    # PREMIUMSNET = Premium + ReinsuranceCeded + ReinsuranceAccepted
    prem    = components.get('_COMPONENT_PREMIUM', 'NA')
    ceded   = components.get('_COMPONENT_REINS_CEDED', 'NA')
    accptd  = components.get('_COMPONENT_REINS_ACCEPTED', 'NA')
    if isinstance(prem, (int, float)) and isinstance(ceded, (int, float)):
        results['LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q'] = round(
            prem + ceded + to_num(accptd), 2)

    # INVGAINLOSSSALE = ProfitSale + LossSale  (loss is negative from parens)
    profit = components.get('_COMPONENT_PROFIT_SALE', 'NA')
    loss   = components.get('_COMPONENT_LOSS_SALE', 'NA')
    if isinstance(profit, (int, float)):
        results['LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q'] = round(
            profit + to_num(loss), 2)

    # NETINCOME = TOTALINCOME + OPERATINGEXP + BENEFITSPAID + BONUSESPAID
    ta  = results.get('LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',  'NA')
    tb  = results.get('LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q', 'NA')
    bp  = results.get('LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q', 'NA')
    bns = results.get('LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',  'NA')
    if all(isinstance(v, (int, float)) for v in [ta, tb, bp, bns]):
        results['LICIPD.REVENUEACCOUNT.NETINCOME.Q'] = round(ta + tb + bp + bns, 2)


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_revenue_account(pdf_path):
    """Extract Revenue Account fields from L-1A/L-1 PDF.

    Returns (results_dict, quarter_string_or_None).
    """
    print(f"\n{'='*70}")
    print(f"Extracting L-1 from: {os.path.basename(pdf_path)}")
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

    gt_col = find_grand_total_col(rows)
    print(f"Grand Total column: {gt_col}")

    quarter = quarter_from_pdf_path(pdf_path)
    print(f"Quarter (from filename): {quarter}")

    label_col = 0   # labels always in column 0 for Revenue Account
    results    = {}
    components = {}
    section    = None

    for i, row in enumerate(rows):
        label = row[label_col] if label_col < len(row) and row[label_col] else ''
        if not label or not label.strip():
            continue
        label = label.strip()

        # Detect section change (section headers have no sub-item prefix)
        new_sect = detect_section(label)
        if new_sect is not None:
            section = new_sect
            print(f"  [SECT:{section.upper()}] row {i}: {label[:55]}")
            continue

        val = parse_value(row[gt_col] if gt_col < len(row) else None)
        prefix = get_subitem_prefix(label)
        code = None
        strategy = None

        # ── Strategy 2: direct label matching — runs FIRST ───────────────────
        # Must precede the shareholders-skip so that TOTAL(A), TOTAL(B),
        # Benefits Paid, Bonuses Paid are extracted even when the
        # "Contribution from Shareholders' A/c" section is active.
        code, strategy = match_direct_label(label)
        if code is not None:
            # Reset section after TOTAL (A) — subsequent rows are unrelated
            if code == 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':
                section = None
            if code.startswith('_COMPONENT_'):
                components[code] = val
                print(f"  [{strategy}] {code.replace('_COMPONENT_', '')} = {val}")
            else:
                results[code] = val
                print(f"  [{strategy}] {code.split('.')[-2]} = {val}")
            continue

        # Skip remaining rows inside the shareholders contribution section
        if section == 'shareholders':
            continue

        # ── Strategy 1: section-aware sub-prefix ─────────────────────────────
        if section in ('premiums', 'investments') and prefix:
            mapped = SECTION_PREFIX_MAP.get((section, prefix))
            if mapped:
                code = mapped
                strategy = f'PREFIX({section},{prefix})'

        # ── Strategy 3: row-index fallback ───────────────────────────────────
        if code is None and i in ROW_INDEX_MAP:
            code = ROW_INDEX_MAP[i]
            strategy = f'ROWIDX({i})'

        if code is None:
            continue

        # Store
        if code.startswith('_COMPONENT_'):
            components[code] = val
            short = code.replace('_COMPONENT_', '')
            print(f"  [{strategy}] {short} = {val}")
        else:
            results[code] = val
            short = code.split('.')[-2] if '.' in code else code
            print(f"  [{strategy}] {short} = {val}")

    doc.close()

    # Compute calculated fields
    apply_calculations(components, results)

    # Summary
    print(f"\n--- RESULTS ({len(results)} fields) ---")
    rev_codes = [c for c in config.COLUMN_CODES if 'REVENUEACCOUNT' in c]
    for code in rev_codes:
        val = results.get(code, 'NA')
        print(f"  {code.split('.')[-2]}: {val}")

    return results, quarter


# ── Expected values from master CSV ──────────────────────────────────────────
EXPECTED_VALUES = {
    '2026-Q1': {
        'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q':      535984.22,
        'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q':     333077.09,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q':   93954.65,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q':  -4745.95,
        'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q':        2799.37,
        'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':      972913.95,
        'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q':      58286.55,
        'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q':     487747.57,
        'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q':        8356.71,
        'LICIPD.REVENUEACCOUNT.NETINCOME.Q':       1527304.78,
    },
    '2025-Q4': {
        'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q':      371293.01,
        'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q':     249068.62,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q':   71999.96,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q':   2461.70,
        'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q':         406.36,
        'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':      696192.51,
        'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q':      47221.05,
        'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q':     312703.36,
        'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q':        3886.30,
        'LICIPD.REVENUEACCOUNT.NETINCOME.Q':       1060003.21,
    },
    '2025-Q3': {
        'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q':      126479.26,
        'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q':      84334.21,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q':   29694.78,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q':  -1599.58,
        'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q':         134.23,
        'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':      239363.15,
        'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q':      16301.19,
        'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q':     105112.82,
        'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q':        1137.54,
        'LICIPD.REVENUEACCOUNT.NETINCOME.Q':        361914.70,
    },
    '2025-Q2': {
        'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q':      119200.39,
        'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q':      82761.16,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q':   18254.37,
        'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q':   2194.87,
        'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q':         130.09,
        'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':      222863.17,
        'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q':      13713.94,
        'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q':      96180.85,
        'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q':         875.26,
        'LICIPD.REVENUEACCOUNT.NETINCOME.Q':        333633.22,
    },
}


if __name__ == '__main__':
    _ensure_utf8_stdout()

    proj      = os.path.join(config.BASE_DIR, 'Project_information')
    sampledir = os.path.join(proj, 'samplepdfs')

    # Each entry: (label, [candidate PDFs]) – script picks the latest by filename date
    test_sets = [
        ('March 2026', [
            os.path.join(proj, 'L-1A- Revenue Account for the period ended 31.03.2026.pdf'),
            os.path.join(proj, 'L-1A- Revenue Account for the period ended 31.03.2025.pdf'),
        ]),
        ('December 2025', [
            os.path.join(sampledir, 'As at December 31, 2025',
                         'L-1A- Revenue Account for the period ended 31.12.2025.pdf'),
            os.path.join(sampledir, 'As at December 31, 2025',
                         'L-1A- Revenue Account for the period ended 31.12.2024.pdf'),
        ]),
        ('September 2025', [
            os.path.join(sampledir, 'As at September 30, 2025',
                         'L-1A- Revenue Account for the quarter ended 30.09.2025 (2).pdf'),
            os.path.join(sampledir, 'As at September 30, 2025',
                         'L-1A- Revenue Account for the quarter ended 30.09.2024 (1).pdf'),
        ]),
        ('June 2025', [
            os.path.join(sampledir, 'As at June 30, 2025',
                         'L-1-Revenue Account for the period ended 30.06.2025.pdf'),
            os.path.join(sampledir, 'As at June 30, 2025',
                         'L-1- Revenue Account for the period ended 30.06.2024.pdf'),
        ]),
    ]

    print(f"Testing {len(test_sets)} Revenue Account PDF sets")
    all_pass = True

    for label, pdf_paths in test_sets:
        print(f"\n{'#'*70}")
        print(f"# Testing: {label}")
        print(f"{'#'*70}")

        latest = select_latest_pdf(pdf_paths)
        if not latest:
            print(f"ERROR: No PDFs found for {label}")
            all_pass = False
            continue

        print(f"Selected (latest): {os.path.basename(latest)}")
        results, quarter = extract_revenue_account(latest)

        print(f"\nQuarter: {quarter}  |  Fields extracted: {len(results)}")

        if quarter and quarter in EXPECTED_VALUES:
            expected = EXPECTED_VALUES[quarter]
            fail_count = 0
            for code, exp_val in expected.items():
                got = results.get(code, 'MISSING')
                # Tolerance 0.02 for floating-point rounding in calculated fields
                if isinstance(got, (int, float)) and abs(got - exp_val) < 0.02:
                    pass
                else:
                    print(f"  VERIFY FAIL: {code.split('.')[-2]} = {got}  (expected {exp_val})")
                    fail_count += 1
                    all_pass = False
            if fail_count == 0:
                print(f"  Verified {len(expected)} values against master CSV")
        else:
            if len(results) < 8:
                print(f"  WARNING: Only {len(results)} fields extracted")
                all_pass = False

    print(f"\n{'='*70}")
    print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print(f"{'='*70}")
