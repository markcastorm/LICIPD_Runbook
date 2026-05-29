# LICIPD — LIC India Public Disclosure Pipeline

Automated quarterly extraction of financial data from LIC India (Life Insurance Corporation of India) public disclosure PDF reports. Extracts 56 fields across 4 PDF types, appends to a master CSV, and generates Excel + ZIP output.

**Provider**: AfricaAI | **Dataset**: LICIPD | **Country**: IND | **Frequency**: Quarterly  
**Source**: https://www.licindia.in/Bottom-Links/Public-disclosure  
**Unit**: Rs. Crore (INR, multiplier 10^7)

---

## Quick Start

```bash
python main.py
```

The pipeline will:
1. Launch a headless Chrome browser and navigate to LIC India's Public Disclosure site
2. Download the latest quarterly PDFs (4 categories, ~5 files)
3. Extract 56 financial fields from the PDFs
4. Append the new quarter to `Master_Data/Master_LICIPD_DATA.csv`
5. Generate `LICIPD_DATA_<timestamp>.xlsx`, `LICIPD_META_<timestamp>.xlsx`, and a ZIP

Output is saved to `output/<YYYYMMDD_HHMMSS>/` and copied to `output/latest/`.

---

## Prerequisites

All packages must be pre-installed. No pip install step.

| Package | Purpose |
|---------|---------|
| `selenium` | Browser automation |
| `undetected-chromedriver` | Bot-detection bypass for Chrome |
| `selenium-stealth` | Additional stealth fingerprinting |
| `PyMuPDF` (fitz) | PDF table extraction |
| `requests` | PDF download via HTTP |
| `openpyxl` | Excel file generation |
| `urllib3` | HTTP warnings suppression |

**Chrome** must be installed (used by undetected-chromedriver).

---

## Project Structure

```
LICIPD_Runbook/
├── main.py                    # Entry point — run this
├── orchestrator.py            # 3-stage pipeline coordinator
├── scraper.py                 # Selenium scraper for LIC India site
├── extractor.py               # PDF extraction for all 4 report types
├── file_generator.py          # Master CSV + Excel/ZIP output
├── config.py                  # All constants, mappings, settings
│
├── Master_Data/
│   └── Master_LICIPD_DATA.csv # Master dataset (append target)
│
├── downloads/
│   └── <YYYYMMDD_HHMMSS>/     # Per-run downloaded PDFs
│       ├── balance_sheet/
│       ├── investments_policyholders/
│       ├── investments_linked/
│       └── revenue_account/
│
├── output/
│   ├── latest/                # Always contains the most recent run output
│   └── <YYYYMMDD_HHMMSS>/     # Per-run output (historical)
│       ├── LICIPD_DATA_<timestamp>.xlsx
│       ├── LICIPD_META_<timestamp>.xlsx
│       └── LICIPD_<timestamp>.zip
│
└── Project_information/
    ├── CLAUDE.md              # Full technical context for AI assistant
    ├── samplepdfs/            # Reference PDFs for 4 quarters
    └── Testfolder/            # Unit test scripts (4/4 ALL PASS)
        ├── test_balance_sheet.py
        ├── test_investments_ph.py
        ├── test_investments_linked.py
        └── test_revenue_account.py
```

---

## Configuration

All settings are in `config.py`. The most commonly changed options:

| Setting | Default | Description |
|---------|---------|-------------|
| `TARGET_YEAR` | `None` | Set to e.g. `"2024 - 2025"` to scrape a specific year. `None` = latest. |
| `TARGET_DATE` | `None` | Set to e.g. `"As at 31 Dec 2024"` to scrape a specific quarter. `None` = latest. |
| `HEADLESS_MODE` | `True` | `False` opens a visible Chrome window (useful for debugging). |
| `WAIT_TIMEOUT` | `60` | Seconds to wait for page elements to load. |

### Example: Scrape a specific historical quarter

```python
# config.py
TARGET_YEAR = "2024 - 2025"
TARGET_DATE = "As at 31 Dec 2024"
```

Reset to `None` after use to resume normal latest-quarter operation.

---

## Pipeline Stages

### Stage 1 — Scraper (`scraper.py`)

Navigates the LIC India Public Disclosure site using Selenium with stealth mode.

**3-level navigation:**
1. Public Disclosure main page → select year (latest or `TARGET_YEAR`)
2. Year page → select date (latest or `TARGET_DATE`)
3. Date page → find and download PDFs by text content matching

**PDF categories downloaded:**

| Category | Form | Typical filename pattern |
|----------|------|--------------------------|
| Balance Sheet | L-3 / L-3A | `L-3A- Balance Sheet as on DD.MM.YYYY.pdf` |
| Investments Policyholders | L-13 | `L-13- Investments- Policyholders as on...pdf` |
| Investments Linked | L-14 | `L-14- Investments -Linked Business as on...pdf` |
| Revenue Account | L-1A / L-1 | `L-1A- Revenue Account for the period ended...pdf` |

Revenue Account may download up to 4 files (current + prior year, L-1 + L-1A variants). The extractor picks the correct one automatically.

**Fallback behavior:** If the latest date has no PDFs yet (just posted), the scraper falls back to the previous date automatically.

### Stage 2 — Extractor (`extractor.py`)

Extracts 56 fields using PyMuPDF (`fitz`) `page.find_tables()`. All table detection is dynamic — no hardcoded row/column positions.

**Key extraction behaviors:**
- **Balance Sheet**: Schedule reference matching (L-12/L-13/L-14) to find Shareholders / Policyholders / Assets Linked rows
- **Investments (L-13, L-14)**: 4-strategy approach per row — label text → sub-item prefix → row number → Hindi keywords
- **Revenue Account**: Section-aware extraction (premiums / investments / shareholders sections); GRAND TOTAL column only; 3 fields are calculated from components
- **Date detection**: Finds `"As at [Month] DD, YYYY"` header patterns dynamically; always picks the most recent date column
- **Hindi support**: Handles PDFs published in Hindi (fitz visual-order Devanagari; inner substring matching for section headers)
- **Dash values (`-`)**: Stored as `NA` — LIC uses dash to mean "not applicable", not zero

**Calculated fields:**

| Field | Formula |
|-------|---------|
| `PREMIUMSNET` | Premium + Reinsurance ceded + Reinsurance accepted |
| `INVGAINLOSSSALE` | Profit on sale + Loss on sale (loss is negative) |
| `NETINCOME` | TOTAL(A) + TOTAL(B) + Benefits Paid + Bonuses Paid |

**Quarter detection priority:** Revenue Account filename date > Balance Sheet date header > scraper URL detection.

### Stage 3 — File Generator (`file_generator.py`)

| Output | Description |
|--------|-------------|
| `Master_LICIPD_DATA.csv` | Master dataset — new quarter row appended (duplicate check prevents re-runs from adding rows) |
| `LICIPD_DATA_<timestamp>.xlsx` | All historical data with styled header, freeze panes |
| `LICIPD_META_<timestamp>.xlsx` | 56-row metadata file (one row per measure) |
| `LICIPD_<timestamp>.zip` | ZIP containing both xlsx files |

---

## Master CSV Structure

`Master_Data/Master_LICIPD_DATA.csv`

- **Row 1**: Column codes (`LICIPD.BALANCESHEET.SHAREHOLDERS.Q`, ...)
- **Row 2**: Human-readable descriptions
- **Row 3+**: Data — quarter label (e.g. `2026-Q1`) + 56 numeric values
- **`NA`**: Field not published by LIC for that quarter

**Quarter labeling** (calendar year):

| Quarter | Period end | Label |
|---------|-----------|-------|
| Q1 | March 31 | `YYYY-Q1` |
| Q2 | June 30 | `YYYY-Q2` |
| Q3 | September 30 | `YYYY-Q3` |
| Q4 | December 31 | `YYYY-Q4` |

---

## 56 Fields

### Balance Sheet — 3 fields (`LICIPD.BALANCESHEET.*`)

| Code suffix | Description |
|------------|-------------|
| `SHAREHOLDERS.Q` | Shareholders' funds (Rs. Crore) |
| `POLICYHOLDERS.Q` | Policyholders' funds (Rs. Crore) |
| `ASSETSLINKEDLIABILITIES.Q` | Assets held to cover linked liabilities (Rs. Crore) |

### Investments Policyholders L-13 — 28 fields (`LICIPD.INVPHS.*`)

17 long-term + 10 short-term individual investment categories + 1 short-term total.  
Categories: GOVTSECS, OTHAPPRSECS, EQUITY, PREFERENCE, MUTUALFUND, DEBENTBOND, DEPOSSSF, OTHSECSBOND, CONTRUTI, SUBSIDIARIES, REALESTATE, INFRASOCIALSECTOR, OTHERNONAPPROVED, PROVISIONDOUBTFUL, TOTAL.

### Investments Linked L-14 — 18 fields (`LICIPD.INVLINKED.*`)

9 long-term + 9 short-term.  
Categories: GOVTSECS, OTHAPPRSECS, EQUITY, PREFERENCE, MUTUALFUND, DEBENTBOND, OTHSECSBOND, INFRASOCIALSECTOR, OTHERNONAPPROVED, NETCURRASST, TOTAL.

### Revenue Account L-1A — 10 fields (`LICIPD.REVENUEACCOUNT.*`)

| Code suffix | Description |
|------------|-------------|
| `PREMIUMSNET.Q` | Premiums earned net (calculated) |
| `INTDIVINCOME.Q` | Interest, dividends & rent — gross |
| `INVGAINLOSSSALE.Q` | Investment gain/loss on sale/redemption (calculated) |
| `INVGAINLOSSREVAL.Q` | Transfer/gain on revaluation/change in fair value |
| `OTHERINCOME.Q` | Other income |
| `TOTALINCOME.Q` | Total (A) — total income |
| `OPERATINGEXP.Q` | Total (B) — operating expenses |
| `BENEFITSPAID.Q` | Benefits paid (net) |
| `BONUSESPAID.Q` | Bonuses paid |
| `NETINCOME.Q` | Net income (calculated) |

---

## Data Coverage

| Quarter range | Count |
|--------------|-------|
| 2022-Q2 through 2026-Q1 | 16 quarters |

Data starts from June 2022 (the earliest available on LIC India's public disclosure site as of 2026).

---

## Accuracy

All extracted values are verified to match source PDFs to the last decimal:
- Indian comma-formatted numbers (e.g. `51,83,692.25`) are correctly parsed as plain floats
- Parenthesised values (e.g. `(6,666.41)`) are stored as negative
- The `SHORTTERM.TOTAL` from L-13 always equals `BALANCESHEET.POLICYHOLDERS` (internal cross-check)
- The `SHORTTERM.TOTAL` from L-14 always equals `BALANCESHEET.ASSETSLINKEDLIABILITIES`

---

## Running Tests

Test scripts are in `Project_information/Testfolder/`. They test extraction against the sample PDFs in `Project_information/samplepdfs/` and `Project_information/*.pdf`.

```bash
cd Project_information/Testfolder
python test_balance_sheet.py       # 4/4 ALL PASS
python test_investments_ph.py      # 4/4 ALL PASS
python test_investments_linked.py  # 4/4 ALL PASS
python test_revenue_account.py     # 4/4 ALL PASS
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Chrome fails to launch | Chrome not installed or wrong version | Install Chrome; `undetected-chromedriver` auto-patches |
| `No year links found` | Site layout changed | Check `_get_year_links()` in `scraper.py` |
| `Core PDFs not yet posted` | Latest quarter PDFs not uploaded yet | Wait for LIC to publish; pipeline auto-falls-back to prior date |
| `NA fields=XX/56` | Normal — some LIC categories not published | Expected; see NA count per quarter in logs |
| `Quarter already in master CSV` | Re-run on same quarter | Normal dedup behavior; CSV not modified |
| `OSError: [WinError 6]` on exit | Harmless Chrome cleanup error on Windows | No action needed |
