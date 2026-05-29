# LICIPD Runbook — Claude Working Context

## Project Status: COMPLETE — Pipeline fully built, tested, and validated

---

## Project Summary

Automated quarterly extraction of LIC India (Life Insurance Corporation of India) public disclosure financial data from PDF reports published at https://www.licindia.in/Bottom-Links/Public-disclosure

Provider: AfricaAI | Dataset: LICIPD | Country: IND | Frequency: Quarterly  
Currency: INR | Unit: Rs. Crore | Multiplier: 5 (10^7)

Pipeline: `python main.py` → orchestrator → scraper → extractor → file_generator  
56 data fields across 4 PDF report types. Master CSV append job (no duplicates).

---

## File Map — All Files Complete

| File | Purpose | Status |
|------|---------|--------|
| `config.py` | All constants, column mappings, PDF label dicts, settings | COMPLETE |
| `scraper.py` | Selenium stealth browser, 3-level LIC site navigation, PDF download | COMPLETE |
| `extractor.py` | fitz-based PDF extraction for all 4 types, 56 fields | COMPLETE |
| `file_generator.py` | Master CSV append, DATA+META xlsx, ZIP output | COMPLETE |
| `orchestrator.py` | 3-stage pipeline coordinator with error isolation | COMPLETE |
| `main.py` | Entry point, logging setup, summary print | COMPLETE |
| `Project_information/Testfolder/test_balance_sheet.py` | Balance Sheet test — 4/4 ALL PASS | COMPLETE |
| `Project_information/Testfolder/test_investments_ph.py` | L-13 test — 4/4 ALL PASS (76 values) | COMPLETE |
| `Project_information/Testfolder/test_investments_linked.py` | L-14 test — 4/4 ALL PASS (45 values) | COMPLETE |
| `Project_information/Testfolder/test_revenue_account.py` | Revenue Account test — 4/4 ALL PASS (40 values) | COMPLETE |

---

## Pipeline Architecture

```
python main.py
  │
  └─► orchestrator.main()
        │
        ├── Stage 1: scraper.download()
        │     Returns: {
        │       'balance_sheet':             [abs_path],
        │       'investments_policyholders': [abs_path],
        │       'investments_linked':        [abs_path],
        │       'revenue_account':           [abs_path, ...],  # up to 4 PDFs
        │       'quarter':                   'YYYY-QN',        # from URL detection
        │       'run_dir':                   'downloads/<ts>/',
        │     }
        │
        ├── Stage 2: extractor.extract(pdf_paths)
        │     Returns: (quarter, {column_code: value_or_'NA'})
        │     Quarter priority: Revenue Account filename > Balance Sheet header > scraper URL
        │
        └── Stage 3: file_generator.generate(quarter, data)
              Returns: {appended, data_xlsx, meta_xlsx, zip, latest_dir}
```

---

## scraper.py — Detailed Design

### Overview
Selenium stealth navigation using `undetected-chromedriver` + `selenium-stealth`. Chrome version auto-detected via `winreg` (Windows) or CLI fallback (Linux). Downloads via `requests` with browser session cookies (faster than browser-triggered downloads).

### 3-Level Site Navigation

**Level 1 — Year selection** (`_get_year_links`, `_select_year`)
- Page: `https://www.licindia.in/Bottom-Links/Public-disclosure`
- Detects year links by: `'public-disclosure' in href` OR `re.search(r'\d{4}[-–]\d{2,4}', href)`
- `config.TARGET_YEAR = None` → selects first link (latest year listed first)
- `config.TARGET_YEAR = "2024 - 2025"` → fuzzy text match

**Level 2 — Date selection** (`_get_date_links`, `_parse_quarter_from_date`)
- Detects date links by: `'as-at-' in href` OR `'as at' in text`
- `config.TARGET_DATE = None` → selects last link (oldest listed first, latest is last)
- `config.TARGET_DATE = "As at 31 Dec 2024"` → fuzzy text match
- **Fallback**: if latest date has no PDFs, walks backward date by date until PDFs found
- When `TARGET_DATE` is set, does NOT fall back silently

**Level 3 — PDF discovery + download**
- Finds all `<a href="*.pdf">` within `<section id="maincontent">`
- Strips size annotations like `(280 KB)` from link text
- Category matchers (text-based, no hardcoded positions):

| Category | Matcher logic |
|----------|--------------|
| Balance Sheet | `re.match(r'L-3[A-Z]?[-\s–]', t)` + `'balance sheet' in lower` |
| Investments PH | `t.startswith('L-13')` + `'investment' in lower` |
| Investments Linked | `t.startswith('L-14')` + NOT `re.match(r'L-14\s*A\b', t)` + investment/linked/assets keyword |
| Revenue Account | `'revenue account' in lower` + priority keyword from `REVENUE_ACCOUNT_PRIORITY` |

- Revenue Account: returns ALL matches at highest-priority keyword (up to 4 PDFs)
- Downloads: `requests.get(url, cookies=browser_cookies)` → validates size ≥ 10 KB

### Key Config Settings

```python
TARGET_YEAR = None        # None = latest; "2024 - 2025" = specific year
TARGET_DATE = None        # None = latest; "As at 31 Dec 2024" = specific date
HEADLESS_MODE = True      # False to open visible Chrome window
WAIT_TIMEOUT = 60         # Seconds to wait for page elements
REVENUE_ACCOUNT_PRIORITY = ["period ended", "quarter ended", "Half year ended"]
```

### Output Structure
```
downloads/<YYYYMMDD_HHMMSS>/
  balance_sheet/            L-3A- Balance Sheet as on DD.MM.YYYY.pdf
  investments_policyholders/ L-13- Investments...pdf
  investments_linked/       L-14- Investments...pdf
  revenue_account/          L-1A- Revenue Account...pdf (1–4 files)
```

---

## extractor.py — Detailed Design

### Overview
Self-contained: all extraction logic inlined, no imports from test scripts. Uses `logging` not `print`. Public API: `extract(pdf_paths_dict)` → `(quarter, data_dict)`.

### `extract(pdf_paths)` Flow
1. Initialise `data = {code: 'NA' for code in config.COLUMN_CODES}`
2. Call `_extract_balance_sheet(path)` → update data + detect quarter
3. Call `_extract_investments_ph(path)` → update data
4. Call `_extract_investments_linked(path)` → update data
5. Call `select_latest_pdf(rev_paths)` → pick newest Revenue Account PDF by DD.MM.YYYY in filename
6. Call `_extract_revenue_account(path)` → update data, override quarter (Revenue Account filename date takes priority)
7. Return `(quarter, data)`

### Shared Utilities

**`parse_value(text)`**
- Empty / None → `'NA'`
- `'NIL'` → `'NA'`
- `'-'` or `'–'` → `'NA'` *(LIC uses dash to mean "not applicable", not zero)*
- `'(1234.56)'` → `-1234.56` (parentheses = negative)
- Indian comma-formatted numbers (`51,83,692.25`) → `5183692.25`

**`detect_date_columns(rows)`**
- Scans all cells for `"as at"` / `"as on"` / Hindi equivalents
- Returns list of `(col_index, date_string, YYYYMMDD_int)` for each date column found
- Caller picks `max(..., key=lambda x: x[2])` for the most recent

**`parse_date_from_text(text)`**
- Handles `DD.MM.YYYY`, `"March 31, 2026"`, Hindi month names + Devanagari numerals
- Returns `(year, month, day)` tuple

**`date_to_quarter(date_text)`**
- Month → `config.MONTH_TO_QUARTER` → `"YYYY-QN"`

### Balance Sheet Extraction (`_extract_balance_sheet`)

Table is on page 0. Two-pass strategy:
1. **Schedule Reference** (primary): finds cell containing `"L-12"`, `"L-13"`, `"L-14"` (or Hindi `"एल-12"`) in the `Schedule Ref.` column → maps to SHAREHOLDERS / POLICYHOLDERS / ASSETSLINKEDLIABILITIES
2. **Label fallback**: if schedule ref not found, matches `'shareholders'`, `'policyholders'`, `'asset held'`/`'assets held'` in row label

### Investments Extraction (`_inv_extract`, shared by L-13 and L-14)

```python
_inv_extract(pdf_path, label_dict, rownum_map, code_prefix)
# label_dict: config.INVPHS_LABELS or config.INVLINKED_LABELS
# rownum_map: _INV_ROWNUM_TO_FIELD (L-13) or _INV_ROWNUM_TO_FIELD_L14 (L-14)
# code_prefix: 'LICIPD.INVPHS' or 'LICIPD.INVLINKED'
```

**Per-row, 4 strategies in order (first match wins):**

| Strategy | Method | Example |
|----------|--------|---------|
| 1 — Label text | `label_dict.get((section, cleaned_label))` then substring fallback | `"Government securities..."` → GOVTSECS |
| 2 — Sub-item prefix | `re.match(r'^\(([a-z]+)\)', raw)` → `_INV_SUBITEM_TO_FIELD` | `(aa)` → EQUITY; `(b)` → MUTUALFUND |
| 3 — Row number | `col0` digit → `rownum_map` | `'1'` → GOVTSECS |
| 4 — Hindi keywords | `_inv_match_hindi(raw, section, prefix)` | `'सरकारी'` in text → GOVTSECS |

**Section detection**: `_inv_detect_section(row)` checks all cells for `"long term"` / `"short term"` / Hindi markers. Section context persists until next section header.

**L-13 vs L-14 differences:**
- L-13 row 6 = PROVISIONDOUBTFUL; L-14 row 6 = NETCURRASST (different `rownum_map`)
- L-14 sub-item `(e)` is a direct value row (not a sub-group header like in L-13)

**Update guard:**
```python
if code not in results or (results[code] == 'NA' and val != 'NA'):
    results[code] = val
```
First-writer wins; a 'NA' can be overwritten by a real value but not vice versa.

### Revenue Account Extraction (`_extract_revenue_account`)

**PDF structure**: 21-column landscape table. Column 20 (0-indexed) = GRAND TOTAL.  
GRAND TOTAL column detected dynamically: `"GRAND TOTAL"` / `"कुल योग"` in row 0.

**`select_latest_pdf(paths)`**: Parses `DD.MM.YYYY` from each filename, returns path with the highest date. Used to pick the current-quarter PDF when 2–4 files are present.

**Section detection**: Scans for English headers (`"premiums earned"`, `"income from investments"`, `"contribution from shareholders"`) or Hindi inner substrings:
- Premiums: `'ीिमयम'`
- Investments: `'वेशो'`
- Shareholders: `'शेयरधारको'`

**Per-row, 2 strategies:**

**Strategy 1 — Section + sub-prefix mapping**

| Section + prefix | Stored as |
|-----------------|-----------|
| premiums (a) | `_COMPONENT_PREMIUM` |
| premiums (b) | `_COMPONENT_REINS_CEDED` |
| premiums (c) | `_COMPONENT_REINS_ACCEPTED` |
| investments (a) | `INTDIVINCOME.Q` |
| investments (b) | `_COMPONENT_PROFIT_SALE` |
| investments (c) | `_COMPONENT_LOSS_SALE` |
| investments (d) | `INVGAINLOSSREVAL.Q` |
| shareholders section | **SKIP** (not extracted) |

**Strategy 2 — Direct label match** (runs BEFORE the shareholders-section skip)  
CRITICAL ordering: Strategy 2 must run first so `TOTAL (A)`, `TOTAL (B)`, Benefits, Bonuses are captured before the shareholders-section skip excludes them.

Hindi direct matches:
- `lower.strip().endswith('(a)')` → TOTALINCOME (catches both `'TOTAL (A)'` and `'कुल (A)'`)
- `lower.strip().endswith('(b)')` → OPERATINGEXP
- `'बोनस' in label` → BONUSESPAID (checked before Benefits to avoid Hindi word overlap)
- `'भुगतान' in label and 'लाभ' in label` → BENEFITSPAID
- `'आय' in label and 'वेश' not in label` → OTHERINCOME

**Calculated fields** (computed after all rows processed):
- `PREMIUMSNET` = Premium + ReinsuranceCeded + ReinsuranceAccepted
- `INVGAINLOSSSALE` = ProfitSale + LossSale (LossSale is typically negative)
- `NETINCOME` = TOTALINCOME + OPERATINGEXP + BENEFITSPAID + BONUSESPAID

---

## file_generator.py — Detailed Design

### `append_to_master_csv(quarter, data)`
1. Reads master CSV → `(header_rows, data_rows)`
2. Checks `{row[0] for row in data_rows}` for duplicates → returns `False` if already present
3. Builds new row: `[quarter] + [_format_value(data.get(code, 'NA')) for code in config.COLUMN_CODES]`
4. Re-writes file: 2 header rows + existing data rows + new row
5. Returns `True`

**`_format_value(val)`**: float whole number → `f"{val:g}"` (e.g. `5.0` → `"5"`); other float → `str(round(val, 6))`; `'NA'`/`None` → `"NA"`.

### `generate(quarter, data)`
1. Appends to master CSV
2. Reads back master CSV for xlsx generation
3. Creates `output/<YYYYMMDD_HHMMSS>/` folder
4. Writes `LICIPD_DATA_<ts>.xlsx` via openpyxl — styled headers (blue/white), freeze at B3
5. Writes `LICIPD_META_<ts>.xlsx` via openpyxl — 56 rows, one per measure, freeze at A2
6. Creates ZIP containing both xlsx files
7. Copies all outputs to `output/latest/`

**Output timestamp**: `datetime.now().strftime('%Y%m%d_%H%M%S')` — ensures multiple same-day runs each get their own folder.

---

## orchestrator.py — Detailed Design

3-stage pipeline with independent error isolation per stage:

```python
# Stage 1 failure → return immediately (no PDFs = cannot continue)
# Stage 2 failure → return immediately (no data = cannot generate output)  
# Stage 3 failure → logged as error; summary['success'] = False
```

**Quarter fallback chain:**
1. `extractor.extract()` detects quarter from PDF content (primary)
2. If extractor returns `None`, use `pdf_paths['quarter']` from scraper URL detection (fallback)
3. If neither available → raise `RuntimeError("Quarter label could not be determined")`

**Return dict:**
```python
{
    'success':   bool,
    'quarter':   'YYYY-QN' or None,
    'appended':  bool,
    'data_xlsx': path or None,
    'meta_xlsx': path or None,
    'zip':       path or None,
    'run_dir':   path,
    'errors':    [str, ...],
}
```

---

## config.py — Key Settings Reference

```python
# ── Scraper ─────────────────────────────────────────────────────────────────
TARGET_YEAR = None        # None=latest  |  "2024 - 2025" to target a year
TARGET_DATE = None        # None=latest  |  "As at 31 Dec 2024" to target a date
HEADLESS_MODE = True      # False for visible Chrome
WAIT_TIMEOUT = 60

# ── Revenue Account PDF priority ─────────────────────────────────────────────
REVENUE_ACCOUNT_PRIORITY = ["period ended", "quarter ended", "Half year ended"]

# ── Quarter mapping ───────────────────────────────────────────────────────────
MONTH_TO_QUARTER = {3: 'Q1', 6: 'Q2', 9: 'Q3', 12: 'Q4'}

# ── Output prefixes ───────────────────────────────────────────────────────────
OUTPUT_DATA_PREFIX = 'LICIPD_DATA_'
OUTPUT_META_PREFIX = 'LICIPD_META_'
OUTPUT_ZIP_PREFIX  = 'LICIPD_'
```

---

## Master CSV Structure

**File**: `Master_Data/Master_LICIPD_DATA.csv`

- **Row 1**: Column codes (`LICIPD.BALANCESHEET.SHAREHOLDERS.Q`, ...)
- **Row 2**: Human-readable descriptions
- **Row 3+**: Data rows — quarter label (e.g. `2026-Q1`) + 56 values
- **`NA`**: Field not published by LIC for that quarter (LIC uses `-` to mean not-applicable)

**Current coverage**: 16 quarters from `2022-Q2` through `2026-Q1`

**Quarter label convention** (calendar year based):

| Month | Quarter | Example |
|-------|---------|---------|
| March (31) | Q1 | `"As at March 31, 2026"` → `2026-Q1` |
| June (30) | Q2 | `"As at June 30, 2025"` → `2025-Q2` |
| September (30) | Q3 | `"As at September 30, 2025"` → `2025-Q3` |
| December (31) | Q4 | `"As at December 31, 2024"` → `2024-Q4` |

---

## Source Website Navigation Details

### Level 1: Public Disclosure Main Page
- URL: `https://www.licindia.in/Bottom-Links/Public-disclosure`
- Year link patterns (INCONSISTENT — all handled):
  - `/web/guest/public-disclosure-2025-26`
  - `/web/guest/public-disclosure-2023-241` (typo: 241 not 24)
  - `/web/guest/2022-2023` (older format)

### Level 2: Year-Specific Date List
- Date link patterns: `'as-at-' in href` OR `'as at' in text`
- Date order: oldest first, latest last
- Fallback: if latest date has no PDFs, walks backward to previous date

### Level 3: Report List Page
- PDF links are in `<section id="maincontent">` with `.pdf` in `href`
- Title text varies widely between quarters (abbreviated, different naming)
- Size labels like `(280 KB)` are stripped before matching

### PDF Viewer Behavior
- LIC PDF URL pattern: `.../documents/20121/UUID/filename.pdf/UUID?t=timestamp`
- Downloaded directly via `requests` using browser session cookies (not through PDF viewer)

---

## Four PDF Report Categories

### 1. Balance Sheet (L-3A / L-3)
- **Matcher**: `re.match(r'L-3[A-Z]?[-\s–]', t)` + `'balance sheet' in lower`
- **Structure**: 2-page PDF; main data on page 0; page 1 = Contingent Liabilities (not needed)
- **3 fields**: Shareholders, Policyholders, Asset Held to Cover Linked Liabilities
- **Extraction**: Schedule Ref column (L-12/L-13/L-14) → SOURCE OF FUNDS section values
- **Hindi**: Hindi schedule refs (`एल-12`) normalised; Hindi month names in date header

### 2. Investments Policyholders (L-13)
- **Matcher**: `t.startswith('L-13')` + `'investment' in lower`
- **Structure**: 1-page PDF, single table, 2 sections (LONG TERM + SHORT TERM)
- **28 fields**: 17 long-term + 11 short-term
- **Link text variants**: `"Investments- Policyholders"`, `"Investments PHs"`, `"Investments Policyholders"`

### 3. Investments Linked Business (L-14)
- **Matcher**: `t.startswith('L-14')` + NOT `re.match(r'L-14\s*A\b', t)` + keyword match
- **Structure**: 1-page PDF, single table, 2 sections (LONG TERM + SHORT TERM)
- **18 fields**: 9 long-term + 9 short-term
- **L-14 sub-item nesting**: Row 3 `(a) Shares` has sub-rows `(aa) Equity`, `(bb) Preference`, `(b) Mutual Funds`, `(d) Debentures`, `(e) Other Securities`
- **Link text variants**: `"Investments -Linked Business"`, `"Investments (Linked Busi)"`, `"Assets held to cover linked liabilities"`
- **EXCLUDE**: L-14A (Investment Additional Information) — excluded by `re.match(r'L-14\s*A\b')`

### 4. Revenue Account (L-1A / L-1)
- **Matcher**: `'revenue account' in lower` + highest-priority keyword from `REVENUE_ACCOUNT_PRIORITY`
- **Structure**: Landscape PDF, 21 columns; GRAND TOTAL = last column (col 20)
- **10 fields** (7 direct + 3 calculated)
- **Multi-PDF**: Downloads up to 4 PDFs; `select_latest_pdf()` picks by DD.MM.YYYY date in filename
- **Section ordering matters**: premiums section → investments section → shareholders section (skip)
- **CRITICAL**: Strategy 2 (direct label match for TOTAL A/B, Benefits, Bonuses) must run BEFORE the shareholders-section skip

---

## Hindi/Multilingual Support

Some quarterly PDFs are published in Hindi (notably June/Q2 quarters).

**fitz behaviour with Devanagari**: renders in visual byte-order, not Unicode logical order. Use inner substrings, not full string matches.

**Section detection substrings** (inner portions of full Hindi labels):
- Premiums: `'ीिमयम'`
- Investments: `'वेशो'`
- Shareholders contribution: `'शेयरधारको'`

**TOTAL(A/B) detection**: `lower.strip().endswith('(a)')` catches both `'TOTAL (A)'` and `'कुल (A)'`

**Month name map**: both English (`'march': 3`) and Hindi (`'मार्च': 3`) in `MONTH_NAME_MAP`

---

## Verified Sample Values

### March 31, 2026 (2026-Q1)
| Field | Value |
|-------|-------|
| BALANCESHEET.SHAREHOLDERS | 150740.33 |
| BALANCESHEET.POLICYHOLDERS | 5333262.11 |
| BALANCESHEET.ASSETSLINKEDLIABILITIES | 61896.94 |
| INVPHS.SHORTTERM.TOTAL | 5333262.11 ← equals POLICYHOLDERS ✓ |
| INVLINKED.SHORTTERM.TOTAL | 61896.94 ← equals ASSETSLINKEDLIABILITIES ✓ |
| REVENUEACCOUNT.PREMIUMSNET | 535984.22 |
| REVENUEACCOUNT.NETINCOME | 1527304.78 |

### December 31, 2024 (2024-Q4) — validated on 2026-05-28
| Field | Value |
|-------|-------|
| BALANCESHEET.SHAREHOLDERS | 95074.51 |
| BALANCESHEET.POLICYHOLDERS | 5183692.25 |
| BALANCESHEET.ASSETSLINKEDLIABILITIES | 43660.57 |
| INVPHS.SHORTTERM.TOTAL | 5183692.25 ← equals POLICYHOLDERS ✓ |
| INVLINKED.SHORTTERM.TOTAL | 43660.57 ← equals ASSETSLINKEDLIABILITIES ✓ |
| REVENUEACCOUNT.PREMIUMSNET | 106891.48 |
| REVENUEACCOUNT.NETINCOME | 313118.27 |

---

## Data Accuracy Notes

- **Indian number formatting** (`51,83,692.25`) → parsed as plain float `5183692.25` (remove all commas)
- **Parentheses negative** (`(6,666.41)`) → stored as `-6666.41`
- **Dash = NA**: LIC uses `-` to mean "not applicable / not held" — extractor stores `'NA'`, not `0`
- **Internal cross-checks always pass**:
  - `L-13 SHORTTERM.TOTAL == BALANCESHEET.POLICYHOLDERS`
  - `L-14 SHORTTERM.TOTAL == BALANCESHEET.ASSETSLINKEDLIABILITIES`
- **Typical NA count**: 11–12 fields per quarter (investment categories LIC doesn't hold: PREFERENCE, DEPOSSSF, CONTRUTI, etc.)

---

## Reference Paths

| Item | Path |
|------|------|
| Entry point | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\main.py` |
| Master CSV | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\Master_Data\Master_LICIPD_DATA.csv` |
| Test scripts | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\Project_information\Testfolder\` |
| Sample PDFs (March 2026) | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\Project_information\*.pdf` |
| Sample PDFs (Dec/Sep/Jun 2025) | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\Project_information\samplepdfs\` |
| Output (latest) | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\output\latest\` |
| Downloads | `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\downloads\` |

---

## Environment

- **Dev**: Windows 11 — `D:\Projects\SIMBA-RUNBOOKS\LICIPD_Runbook\`
- **Prod**: Docker Linux Ubuntu container
- **Python**: 3.11+
- **All packages pre-installed** — no `pip install`, no `requirements.txt`
- **Entry point**: `python main.py`
- **File paths**: Always use `os.path.join()` — never hardcode separators

---

## Progress Log

### 2026-05-28: Analysis + Full Pipeline Build
- Analysed all reference files, screenshots, sample PDFs (4 quarters)
- Built all 10 files in order: config → test scripts → pipeline files
- Test results: all 4 test scripts 4/4 ALL PASS (161 values verified across 4 quarters)
- End-to-end pipeline test: `python main.py` → SUCCESS → 2026-Q1 extracted and appended

### 2026-05-28: Historical Quarter Test
- Tested `TARGET_YEAR="2024 - 2025"`, `TARGET_DATE="As at 31 Dec 2024"` → SUCCESS
- All 3 pipeline stages completed; 2024-Q4 extracted and appended
- Data accuracy verified: all values match source PDFs to last decimal

### 2026-05-29: Repository Cleanup
- Master CSV restored from sample data (`LICIPD_DATA_20260525 - Sheet1.csv`) — 16 quarters, 2022-Q2 through 2026-Q1
- Test scripts moved to `Project_information/Testfolder/`
- `README.md` created at project root
- `CLAUDE.md` updated with full completed-pipeline detail
