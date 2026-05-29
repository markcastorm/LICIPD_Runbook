"""
Extractor for LIC India Public Disclosure PDFs.

Combines the four proven extraction routines (Balance Sheet, Investments PH,
Investments Linked, Revenue Account) into a single public API:

    quarter, data = extract(pdf_paths)

where `pdf_paths` is the dict returned by scraper.download():
    {
        'balance_sheet':             [abs_path],
        'investments_policyholders': [abs_path],
        'investments_linked':        [abs_path],
        'revenue_account':           [abs_path, ...],   # up to 2; latest is selected
    }

Returns:
    quarter  : 'YYYY-QN' string, or None if detection failed
    data     : {column_code: value_or_'NA'} for all 56 codes in config.COLUMN_CODES
"""

import os
import re
import logging
from datetime import datetime

import fitz   # PyMuPDF

import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Shared utilities
# ══════════════════════════════════════════════════════════════════════════════

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
    'जनवरी': 1,
    'फ़रवरी': 2,
    'फरवरी': 2,
    'मार्च': 3,
    'अप्रैल': 4,
    'मई': 5,
    'जून': 6,
    'जुलाई': 7,
    'अगस्त': 8,
    'सितंबर': 9,
    'अक्तूबर': 10,
    'नवंबर': 11,
    'दिसंबर': 12,
}


def parse_value(text):
    """Parse a numeric value from PDF cell text.

    Handles: Indian comma formatting, parentheses=negative, NIL/dash=NA.
    """
    if not text or not text.strip():
        return 'NA'
    text = text.strip()
    if text.upper() == 'NIL':
        return 'NA'
    if text in ['-', '–', '—', '']:
        return 'NA'
    is_negative = text.startswith('(') and text.endswith(')')
    if is_negative:
        text = text[1:-1].strip()
    text = text.replace(',', '')
    try:
        val = float(text)
        return -val if is_negative else val
    except ValueError:
        return 'NA'


def parse_date_from_text(text):
    """Parse date from header cell text.

    Handles: 'As at March 31, 2026', 'As at Sept. 30, 2025',
             'As at 31.12.2025', '30 जून, 2025 तक'.
    Returns (day, month, year) tuple or None.
    """
    if not text:
        return None
    text = text.replace('\n', ' ').strip()

    m = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    m = re.search(r'(\w+\.?)\s+(\d{1,2}),?\s*(\d{4})', text)
    if m:
        month = MONTH_NAME_MAP.get(m.group(1).lower(), 0)
        if month > 0:
            return int(m.group(2)), month, int(m.group(3))

    # Hindi: "30 जून, 2025 तक"
    m = re.search(r'(\d{1,2})\s+(\S+),?\s*(\d{4})', text)
    if m:
        month = MONTH_NAME_MAP.get(m.group(2).strip().rstrip(','), 0)
        if month > 0:
            return int(m.group(1)), month, int(m.group(3))

    return None


def detect_date_columns(rows):
    """Detect date-bearing columns in header rows.

    Returns list of (col_index, date_text, sortable_int) tuples.
    """
    date_cols = []
    for row in rows[:5]:
        for j, cell in enumerate(row):
            if not cell:
                continue
            cell_clean = cell.replace('\n', ' ').strip()
            if (re.search(r'as\s+(at|on)\s+', cell_clean, re.IGNORECASE)
                    or 'तक' in cell_clean   # Hindi "तक"
                    or re.search(r'\d{1,2}\s+\S+,?\s*\d{4}', cell_clean)):
                parsed = parse_date_from_text(cell_clean)
                if parsed:
                    d, m, y = parsed
                    date_cols.append((j, cell_clean, y * 10000 + m * 100 + d))
    return date_cols


def date_to_quarter(date_text):
    """Convert date header text to 'YYYY-QN' label."""
    if not date_text:
        return None
    parsed = parse_date_from_text(date_text)
    if not parsed:
        return None
    _, month, year = parsed
    q = config.MONTH_TO_QUARTER.get(month)
    return f"{year}-{q}" if q else None


# ══════════════════════════════════════════════════════════════════════════════
# Balance Sheet (L-3 / L-3A)
# ══════════════════════════════════════════════════════════════════════════════

_BS_SCHEDULE_REF_MAP = {
    'L-12': 'LICIPD.BALANCESHEET.SHAREHOLDERS.Q',
    'L-13': 'LICIPD.BALANCESHEET.POLICYHOLDERS.Q',
    'L-14': 'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
}


def _extract_balance_sheet(pdf_path):
    """Extract 3 Balance Sheet values. Returns (results_dict, date_text)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    tables = page.find_tables()
    results = {}
    date_detected = None

    if not tables.tables:
        logger.warning("Balance Sheet: no tables found on page 1")
        doc.close()
        return results, date_detected

    best = max(tables.tables, key=lambda t: len(t.extract()))
    rows = best.extract()

    date_cols = detect_date_columns(rows)
    if not date_cols:
        logger.warning("Balance Sheet: no date columns detected")
        doc.close()
        return results, date_detected

    latest = max(date_cols, key=lambda x: x[2])
    latest_col, date_detected = latest[0], latest[1]
    logger.debug(f"Balance Sheet: using col={latest_col} date='{date_detected}'")

    # Find APPLICATION OF FUNDS section start
    app_row = None
    for i, row in enumerate(rows):
        if any(cell and 'application of funds' in cell.lower() for cell in row):
            app_row = i
            break
    search_start = app_row if app_row is not None else 0

    # Strategy 1: Schedule Reference column (L-12, L-13, L-14)
    sched_col = None
    for j, cell in enumerate(rows[0]):
        if cell and ('schedule' in cell.lower()
                     or 'अनुसूची' in cell):
            sched_col = j
            break

    if sched_col is not None:
        for i, row in enumerate(rows):
            if i <= search_start:
                continue
            if sched_col < len(row) and row[sched_col]:
                ref = row[sched_col].strip()
                ref_n = re.sub(r'L\s+(\d+)', r'L-\1',
                               ref.replace('एल', 'L').replace('–', '-'))
                for sref, code in _BS_SCHEDULE_REF_MAP.items():
                    if sref in ref or sref in ref_n:
                        val = parse_value(row[latest_col] if latest_col < len(row) else None)
                        results[code] = val
                        logger.debug(f"  BS [{sref}]: {code.split('.')[-2]} = {val}")
                        break

    # Strategy 2: text label fallback
    if len(results) < 3:
        for i, row in enumerate(rows):
            if i <= search_start:
                continue
            label = None
            for cell in row:
                if cell and cell.strip():
                    label = cell.strip()
                    break
            if not label:
                continue
            cleaned = re.sub(r'[^\x00-\x7f]', '', label.lower()).strip()
            cleaned = re.sub(r'^\d+\.?\s*', '', cleaned).rstrip(':').strip()
            for pattern, code in config.BALANCE_SHEET_LABELS.items():
                if code not in results and pattern in cleaned:
                    val = parse_value(row[latest_col] if latest_col < len(row) else None)
                    if val != 'NA':
                        results[code] = val
                        logger.debug(f"  BS [label]: {code.split('.')[-2]} = {val}")
                    break

    doc.close()
    logger.info(f"Balance Sheet: {len(results)}/3 fields extracted  quarter={date_to_quarter(date_detected)}")
    return results, date_detected


# ══════════════════════════════════════════════════════════════════════════════
# Investments (shared helpers for L-13 and L-14)
# ══════════════════════════════════════════════════════════════════════════════

_INV_SUBITEM_TO_FIELD = {
    'aa': 'EQUITY',
    'bb': 'PREFERENCE',
    'b':  'MUTUALFUND',
    'd':  'DEBENTBOND',
    'e':  'OTHSECSBOND',
    'i':  'OTHSECSBOND',
    'f':  'SUBSIDIARIES',
    'g':  'REALESTATE',
}

_INV_ROWNUM_TO_FIELD = {
    '1': 'GOVTSECS',
    '2': 'OTHAPPRSECS',
    '4': 'INFRASOCIALSECTOR',
    '5': 'OTHERNONAPPROVED',
    '6': 'PROVISIONDOUBTFUL',
}

_INV_ROWNUM_TO_FIELD_L14 = {
    '1': 'GOVTSECS',
    '2': 'OTHAPPRSECS',
    '4': 'INFRASOCIALSECTOR',
    '5': 'OTHERNONAPPROVED',
    '6': 'NETCURRASST',
}

_INV_SECTION_MARKERS = {
    'long_term': [
        'long term', 'long-term',
        'लंबी अविध',
        'लंबी अवधि',
        'दीर्घकालिक',
    ],
    'short_term': [
        'short term', 'short-term',
        'लघु अविध',
        'लघु अवधि',
        'अल्पकालिक',
    ],
}

_INV_TOTAL_MARKERS = ['total', 'कुल', 'योग']

_INV_HINDI_KEYWORDS = {
    'GOVTSECS':          ['सरकारी'],
    'OTHAPPRSECS':       ['ˢीकृ त Ůितभूितयां'],
    'EQUITY':            ['इिƣटी', 'इक्विटी'],
    'PREFERENCE':        ['वरीयता'],
    'MUTUALFUND':        ['ʄूचुअल', 'म्यूचुअल'],
    'DEBENTBOND':        ['िडबŐचर', 'डिबेंचर'],
    'OTHSECSBOND':       ['बॉȵ्स', 'बॉन्ड'],
    'SUBSIDIARIES':      ['सहायक'],
    'REALESTATE':        ['एːेट', 'रियल', 'संपिɅ'],
    'INFRASOCIALSECTOR': ['बुिनयादी', 'ढांचे'],
    'OTHERNONAPPROVED':  ['अलावा'],
    'PROVISIONDOUBTFUL': ['Ůावधान', 'संिद'],
}


def _inv_clean_label(text):
    if not text:
        return ''
    t = text.strip().replace('\n', ' ')
    t = re.sub(r'^\d+\.?\s*', '', t).strip()
    t = re.sub(r'^\([a-z]+\)\s*', '', t).strip()
    t = re.sub(r'[:–—\-]+$', '', t).strip()
    return re.sub(r'\s+', ' ', t).lower()


def _inv_find_label_col(rows):
    for row in rows[:5]:
        for j, cell in enumerate(row):
            if not cell:
                continue
            if ('particulars' in cell.lower()
                    or 'िववरण' in cell):
                return j
    if not rows:
        return 1
    num_cols = len(rows[0])
    scores = [0] * num_cols
    for row in rows[3:]:
        for j, cell in enumerate(row[:num_cols]):
            if cell and cell.strip() and not re.match(r'^[\d,.()\-–\s]*$', cell.strip()):
                scores[j] += 1
    return max(range(num_cols), key=lambda j: scores[j]) if any(scores) else 1


def _inv_detect_section(row):
    all_text = ' '.join((c or '').replace('\n', ' ').strip().lower() for c in row)
    for section, markers in _INV_SECTION_MARKERS.items():
        for m in markers:
            if m in all_text:
                return section
    return None


def _inv_is_total(label_text):
    return bool(label_text) and label_text.strip().lower() in _INV_TOTAL_MARKERS


def _inv_get_prefix(text):
    if not text:
        return None
    m = re.match(r'^\s*\(([a-z]+)\)', text.strip())
    return m.group(1) if m else None


def _inv_match_hindi(label, section, code_prefix):
    if not label:
        return None
    section_upper = 'LONGTERM' if section == 'long_term' else 'SHORTTERM'
    for field_suffix, keywords in _INV_HINDI_KEYWORDS.items():
        for kw in keywords:
            if kw in label:
                if (field_suffix == 'OTHAPPRSECS'
                        and 'अलावा' in label):
                    continue
                code = f'{code_prefix}.{section_upper}.{field_suffix}.Q'
                if code in config.COLUMN_CODES:
                    return code
    return None


def _inv_extract(pdf_path, label_dict, rownum_map, code_prefix):
    """Core investments extraction used by both L-13 and L-14."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    tables = page.find_tables()

    if not tables.tables:
        logger.warning(f"{code_prefix}: no tables found")
        doc.close()
        return {}, None

    best = max(tables.tables, key=lambda t: len(t.extract()))
    rows = best.extract()

    date_cols = detect_date_columns(rows)
    if not date_cols:
        logger.warning(f"{code_prefix}: no date columns detected")
        doc.close()
        return {}, None

    latest = max(date_cols, key=lambda x: x[2])
    latest_col, date_detected = latest[0], latest[1]

    label_col = _inv_find_label_col(rows)
    results = {}
    section = None

    for i, row in enumerate(rows):
        new_sect = _inv_detect_section(row)
        if new_sect:
            section = new_sect
            continue
        if section is None:
            continue

        raw = row[label_col].strip() if label_col < len(row) and row[label_col] else ''
        if not raw:
            continue

        col0 = row[0].strip() if row[0] else ''
        row_num = col0 if re.match(r'^\d$', col0) else ''

        val = parse_value(row[latest_col] if latest_col < len(row) else None)

        # TOTAL row
        if _inv_is_total(raw):
            code = f'{code_prefix}.SHORTTERM.TOTAL.Q'
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                logger.debug(f"  [{code_prefix}] TOTAL = {val}")
            continue

        prefix = _inv_get_prefix(raw)
        if prefix in ('a', 'c'):
            continue

        section_upper = 'LONGTERM' if section == 'long_term' else 'SHORTTERM'
        code = None
        strat = None

        # Strategy 1: English label
        cleaned = _inv_clean_label(raw)
        if cleaned:
            s1 = label_dict.get((section, cleaned))
            if s1 is None:
                for cfg_key, cfg_code in label_dict.items():
                    if cfg_key[0] != section:
                        continue
                    if cfg_key[1] in cleaned or (cleaned in cfg_key[1] and len(cleaned) > 3):
                        s1 = cfg_code
                        break
            if s1:
                code, strat = s1, 'LABEL'

        # Strategy 2: Sub-item prefix
        if prefix and prefix in _INV_SUBITEM_TO_FIELD:
            s2 = f'{code_prefix}.{section_upper}.{_INV_SUBITEM_TO_FIELD[prefix]}.Q'
            if s2 in config.COLUMN_CODES and code is None:
                code, strat = s2, 'PREFIX'

        # Strategy 3: Row number
        if not code and row_num and row_num in rownum_map:
            s3 = f'{code_prefix}.{section_upper}.{rownum_map[row_num]}.Q'
            if s3 in config.COLUMN_CODES:
                code, strat = s3, 'ROWNUM'

        # Strategy 4: Hindi keywords
        if not code:
            s4 = _inv_match_hindi(raw, section, code_prefix)
            if s4:
                code, strat = s4, 'HINDI'

        # Special: unlabeled Other Securities (L-13 (e) header pattern)
        if (not code and not prefix and not row_num
                and cleaned and 'other securities' in cleaned):
            s5 = f'{code_prefix}.{section_upper}.OTHSECSBOND.Q'
            if s5 in config.COLUMN_CODES:
                code, strat = s5, 'SPECIAL'

        if code:
            if code not in results or (results[code] == 'NA' and val != 'NA'):
                results[code] = val
                logger.debug(f"  [{strat}] {code.split('.')[-2]} = {val}")

    doc.close()
    return results, date_detected


def _extract_investments_ph(pdf_path):
    results, date = _inv_extract(
        pdf_path, config.INVPHS_LABELS, _INV_ROWNUM_TO_FIELD, 'LICIPD.INVPHS'
    )
    logger.info(f"Investments PH: {len(results)}/28 fields  quarter={date_to_quarter(date)}")
    return results, date


def _extract_investments_linked(pdf_path):
    results, date = _inv_extract(
        pdf_path, config.INVLINKED_LABELS, _INV_ROWNUM_TO_FIELD_L14, 'LICIPD.INVLINKED'
    )
    logger.info(f"Investments Linked: {len(results)}/18 fields  quarter={date_to_quarter(date)}")
    return results, date


# ══════════════════════════════════════════════════════════════════════════════
# Revenue Account (L-1A / L-1)
# ══════════════════════════════════════════════════════════════════════════════

_REV_EN_SECT_PREMIUMS     = 'premiums earned'
_REV_EN_SECT_INVESTMENTS  = 'income from investments'
_REV_EN_SECT_SHAREHOLDERS = 'contribution from shareholders'

# fitz renders Devanagari in visual byte-order; use inner substrings:
_REV_HI_SECT_PREMIUMS     = 'ीिमयम'   # 'ीिमयम'
_REV_HI_SECT_INVESTMENTS  = 'वेशो'          # 'वेशो'
_REV_HI_SECT_SHAREHOLDERS = 'शेयरधारको'  # 'शेयरधारको'

_REV_SECTION_PREFIX_MAP = {
    ('premiums',    'a'): '_COMPONENT_PREMIUM',
    ('premiums',    'b'): '_COMPONENT_REINS_CEDED',
    ('premiums',    'c'): '_COMPONENT_REINS_ACCEPTED',
    ('investments', 'a'): 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    ('investments', 'b'): '_COMPONENT_PROFIT_SALE',
    ('investments', 'c'): '_COMPONENT_LOSS_SALE',
    ('investments', 'd'): 'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
}

_REV_ROW_INDEX_MAP = {
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

_REV_DIRECT_EN = {
    'other income':         'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q',
    'total (a)':            'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
    'total (b)':            'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
    'benefits paid (net)':  'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'benefits paid(net)':   'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'interim bonuses paid': 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
    'bonuses paid':         'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
}


def _rev_parse_date_from_filename(pdf_path):
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', os.path.basename(pdf_path))
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def select_latest_pdf(pdf_paths):
    """Return the PDF with the latest DD.MM.YYYY date in its filename."""
    dated = [
        (p, _rev_parse_date_from_filename(p))
        for p in pdf_paths if os.path.exists(p)
    ]
    valid = [(p, d) for p, d in dated if d is not None]
    if valid:
        return max(valid, key=lambda x: x[1])[0]
    existing = [p for p in pdf_paths if os.path.exists(p)]
    return existing[0] if existing else None


def _rev_quarter_from_pdf(pdf_path):
    d = _rev_parse_date_from_filename(pdf_path)
    if d:
        q = config.MONTH_TO_QUARTER.get(d.month)
        if q:
            return f"{d.year}-{q}"
    return None


def _rev_find_gt_col(rows):
    for row in rows[:4]:
        for i, cell in enumerate(row):
            if cell:
                txt = str(cell).strip()
                if 'GRAND TOTAL' in txt.upper() or 'कुल योग' in txt:
                    return i
    return len(rows[0]) - 1 if rows else 0


def _rev_get_prefix(label):
    m = re.match(r'^\s*\(([a-zA-Z])\)', (label or '').strip())
    return m.group(1).lower() if m else None


def _rev_detect_section(label):
    if not label or not label.strip():
        return None
    if _rev_get_prefix(label) is not None:
        return None
    lower = label.strip().lower()
    if _REV_EN_SECT_PREMIUMS in lower:
        return 'premiums'
    if _REV_EN_SECT_INVESTMENTS in lower:
        return 'investments'
    if _REV_EN_SECT_SHAREHOLDERS in lower:
        return 'shareholders'
    if _REV_HI_SECT_PREMIUMS in label:
        return 'premiums'
    if _REV_HI_SECT_INVESTMENTS in label:
        return 'investments'
    if _REV_HI_SECT_SHAREHOLDERS in label:
        return 'shareholders'
    return None


def _rev_match_direct(label):
    """Returns (code_or_component, strategy) or (None, None)."""
    if not label or _rev_get_prefix(label) is not None:
        return None, None
    lower = label.strip().lower()

    for pattern, code in _REV_DIRECT_EN.items():
        if pattern in lower:
            return code, 'EN'

    # Hindi TOTAL(A)/(B): both 'TOTAL (A)' and 'कुल (A)' end with '(a)'
    if lower.strip().endswith('(a)'):
        return 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q', 'HI'
    if lower.strip().endswith('(b)'):
        return 'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q', 'HI'

    # Hindi Bonuses — check before Benefits since both use 'भुगतान'
    if 'बोनस' in label:       # बोनस
        return 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q', 'HI'
    if 'भुगतान' in label and 'लाभ' in label:  # भुगतान + लाभ
        return 'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q', 'HI'
    # Hindi Other Income: 'आय' without 'वेश' (investments header contains वेश)
    if 'आय' in label and 'वेश' not in label:  # आय, not वेश
        return 'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q', 'HI'

    return None, None


def _rev_apply_calculations(components, results):
    def to_num(v):
        return v if isinstance(v, (int, float)) else 0.0

    prem   = components.get('_COMPONENT_PREMIUM', 'NA')
    ceded  = components.get('_COMPONENT_REINS_CEDED', 'NA')
    accptd = components.get('_COMPONENT_REINS_ACCEPTED', 'NA')
    if isinstance(prem, (int, float)) and isinstance(ceded, (int, float)):
        results['LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q'] = round(
            prem + ceded + to_num(accptd), 2)

    profit = components.get('_COMPONENT_PROFIT_SALE', 'NA')
    loss   = components.get('_COMPONENT_LOSS_SALE', 'NA')
    if isinstance(profit, (int, float)):
        results['LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q'] = round(
            profit + to_num(loss), 2)

    ta  = results.get('LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',  'NA')
    tb  = results.get('LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q', 'NA')
    bp  = results.get('LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q', 'NA')
    bns = results.get('LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',  'NA')
    if all(isinstance(v, (int, float)) for v in [ta, tb, bp, bns]):
        results['LICIPD.REVENUEACCOUNT.NETINCOME.Q'] = round(ta + tb + bp + bns, 2)


def _extract_revenue_account(pdf_path):
    """Extract 10 Revenue Account fields (7 direct + 3 calculated). Returns (results, quarter)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    tables = page.find_tables()

    if not tables.tables:
        logger.warning("Revenue Account: no tables found")
        doc.close()
        return {}, None

    best = max(tables.tables, key=lambda t: len(t.extract()))
    rows = best.extract()

    gt_col = _rev_find_gt_col(rows)
    quarter = _rev_quarter_from_pdf(pdf_path)

    results    = {}
    components = {}
    section    = None

    for i, row in enumerate(rows):
        label = row[0] if row and row[0] else ''
        if not label or not label.strip():
            continue
        label = label.strip()

        new_sect = _rev_detect_section(label)
        if new_sect is not None:
            section = new_sect
            continue

        val = parse_value(row[gt_col] if gt_col < len(row) else None)
        prefix = _rev_get_prefix(label)

        # Strategy 2: direct label match — runs BEFORE shareholders-section skip
        code, strat = _rev_match_direct(label)
        if code is not None:
            if code == 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q':
                section = None
            target = components if code.startswith('_COMPONENT_') else results
            target[code] = val
            logger.debug(f"  [REV-{strat}] {code.split('.')[-2] if '.' in code else code} = {val}")
            continue

        # Skip all sub-items within shareholders contribution section
        if section == 'shareholders':
            continue

        # Strategy 1: section-aware sub-prefix
        if section in ('premiums', 'investments') and prefix:
            code = _REV_SECTION_PREFIX_MAP.get((section, prefix))
            strat = f'PREFIX({section},{prefix})'

        # Strategy 3: row-index fallback
        if code is None and i in _REV_ROW_INDEX_MAP:
            code = _REV_ROW_INDEX_MAP[i]
            strat = f'ROWIDX({i})'

        if code is None:
            continue

        target = components if code.startswith('_COMPONENT_') else results
        target[code] = val
        logger.debug(f"  [REV-{strat}] {code.split('.')[-2] if '.' in code else code} = {val}")

    doc.close()
    _rev_apply_calculations(components, results)
    logger.info(f"Revenue Account: {len(results)}/10 fields  quarter={quarter}")
    return results, quarter


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def extract(pdf_paths):
    """
    Extract all 56 fields from downloaded PDFs.

    Args:
        pdf_paths: dict with keys 'balance_sheet', 'investments_policyholders',
                   'investments_linked', 'revenue_account' — each a list of paths.
                   Revenue Account may contain 2 paths; the latest is selected.

    Returns:
        (quarter, data) where:
            quarter : 'YYYY-QN' string or None
            data    : {column_code: value_or_'NA'} for all 56 codes
    """
    data = {code: 'NA' for code in config.COLUMN_CODES}
    quarter = None

    # ── Balance Sheet ────────────────────────────────────────────────────────
    bs_paths = pdf_paths.get('balance_sheet', [])
    if bs_paths:
        bs_path = bs_paths[0]
        if os.path.exists(bs_path):
            bs_results, bs_date = _extract_balance_sheet(bs_path)
            data.update({k: v for k, v in bs_results.items() if k in data})
            if not quarter:
                quarter = date_to_quarter(bs_date)
        else:
            logger.warning(f"Balance Sheet PDF not found: {bs_path}")

    # ── Investments Policyholders (L-13) ─────────────────────────────────────
    invph_paths = pdf_paths.get('investments_policyholders', [])
    if invph_paths:
        invph_path = invph_paths[0]
        if os.path.exists(invph_path):
            invph_results, invph_date = _extract_investments_ph(invph_path)
            data.update({k: v for k, v in invph_results.items() if k in data})
            if not quarter:
                quarter = date_to_quarter(invph_date)
        else:
            logger.warning(f"Investments PH PDF not found: {invph_path}")

    # ── Investments Linked Business (L-14) ───────────────────────────────────
    invlnk_paths = pdf_paths.get('investments_linked', [])
    if invlnk_paths:
        invlnk_path = invlnk_paths[0]
        if os.path.exists(invlnk_path):
            invlnk_results, invlnk_date = _extract_investments_linked(invlnk_path)
            data.update({k: v for k, v in invlnk_results.items() if k in data})
            if not quarter:
                quarter = date_to_quarter(invlnk_date)
        else:
            logger.warning(f"Investments Linked PDF not found: {invlnk_path}")

    # ── Revenue Account (L-1A / L-1) — pick latest of up to 2 PDFs ──────────
    rev_paths = pdf_paths.get('revenue_account', [])
    if rev_paths:
        latest = select_latest_pdf(rev_paths)
        if latest and os.path.exists(latest):
            rev_results, rev_quarter = _extract_revenue_account(latest)
            data.update({k: v for k, v in rev_results.items() if k in data})
            if rev_quarter:
                quarter = rev_quarter   # filename date is most reliable
        else:
            logger.warning(f"No valid Revenue Account PDF found in: {rev_paths}")

    missing = [c for c in config.COLUMN_CODES if data.get(c) == 'NA']
    logger.info(
        f"Extraction complete: {len(config.COLUMN_CODES) - len(missing)}/56 fields  "
        f"quarter={quarter}  missing={len(missing)}"
    )
    return quarter, data
