import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
OUTPUT_DIR   = os.path.join(BASE_DIR, 'output')
MASTER_DIR   = os.path.join(BASE_DIR, 'Master_Data')
MASTER_CSV   = os.path.join(MASTER_DIR, 'Master_LICIPD_DATA.csv')

# ── Source ────────────────────────────────────────────────────────────────────
BASE_URL = 'https://www.licindia.in/Bottom-Links/Public-disclosure'

# ── Browser ───────────────────────────────────────────────────────────────────
HEADLESS_MODE  = True
WAIT_TIMEOUT   = 60
PAGE_LOAD_WAIT = 5       # seconds to wait after page load
CLICK_DELAY    = (2, 4)  # random delay range (min, max) between clicks

# ── Target Selection (None = auto-detect latest) ─────────────────────────────
TARGET_YEAR = None        # e.g. "2025 - 2026" or None for latest
TARGET_DATE = None        # e.g. "As at March 31, 2026" or None for latest

# ── Backfill ──────────────────────────────────────────────────────────────────
# BACKFILL_ENABLED: True  = auto-detect gaps in master CSV and process all
#                           missing quarters in one run (recommended).
#                  False  = process only the single latest available quarter.
BACKFILL_ENABLED     = True
BACKFILL_MAX_WORKERS = 4   # parallel workers for PDF extraction

# ── State tracking ────────────────────────────────────────────────────────────
# SKIP_IF_PROCESSED: True  = skip the run if the detected quarter was already
#                            processed (logged as NO NEW DATA).
#                   False  = bypass the check and run the full pipeline anyway.
SKIP_IF_PROCESSED = True
STATE_FILE = os.path.join(BASE_DIR, 'state.json')

# ── Revenue Account PDF Selection Priority ────────────────────────────────────
# Order of preference when multiple Revenue Account PDFs exist
# Options: "period ended", "quarter ended", "Half year ended"
REVENUE_ACCOUNT_PRIORITY = ["period ended", "quarter ended", "Half year ended"]

# ── Output ────────────────────────────────────────────────────────────────────
DATASET_NAME = 'LICIPD'
OUTPUT_DATA_PREFIX = 'LICIPD_DATA_'
OUTPUT_META_PREFIX = 'LICIPD_META_'
OUTPUT_ZIP_PREFIX  = 'LICIPD_'

# ── PDF Search Patterns (for finding links on report list page) ───────────────
# Each pattern is a list of keyword groups. ALL groups must match (AND logic).
# Within a group, any keyword matching is sufficient (OR logic).
PDF_SEARCH_PATTERNS = {
    'balance_sheet': {
        'keywords': [['Balance Sheet']],
        'form_prefix': ['L-3', 'L-3A'],
    },
    'investments_policyholders': {
        'keywords': [['Investments'], ['Policyholders', 'PHs']],
        'form_prefix': ['L-13'],
    },
    'investments_linked': {
        'keywords': [
            # Either "Investments" + "Linked" OR "Assets held to cover linked"
        ],
        'form_prefix': ['L-14'],
        'alt_keywords': [['Assets held to cover linked']],
    },
    'revenue_account': {
        'keywords': [['Revenue Account']],
        'form_prefix': ['L-1A', 'L-1'],
    },
}

# ── Column Mapping: All 56 Data Fields ────────────────────────────────────────
# Ordered exactly as they appear in the master CSV

COLUMN_CODES = [
    'LICIPD.BALANCESHEET.SHAREHOLDERS.Q',
    'LICIPD.BALANCESHEET.POLICYHOLDERS.Q',
    'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
    # -- Investments Policyholders LONG TERM (14 fields)
    'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q',
    'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q',
    'LICIPD.INVPHS.LONGTERM.EQUITY.Q',
    'LICIPD.INVPHS.LONGTERM.PREFERENCE.Q',
    'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q',
    'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q',
    'LICIPD.INVPHS.LONGTERM.DEPOSSSF.Q',
    'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q',
    'LICIPD.INVPHS.LONGTERM.CONTRUTI.Q',
    'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q',
    'LICIPD.INVPHS.LONGTERM.REALESTATE.Q',
    'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q',
    'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q',
    'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q',
    # -- Investments Policyholders SHORT TERM (11 fields)
    'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q',
    'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q',
    'LICIPD.INVPHS.SHORTTERM.EQUITY.Q',
    'LICIPD.INVPHS.SHORTTERM.PREFERENCE.Q',
    'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q',
    'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q',
    'LICIPD.INVPHS.SHORTTERM.OTHSECSBOND.Q',
    'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q',
    'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q',
    'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q',
    'LICIPD.INVPHS.SHORTTERM.TOTAL.Q',
    # -- Investments Linked Business LONG TERM (9 fields)
    'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q',
    'LICIPD.INVLINKED.LONGTERM.OTHAPPRSECS.Q',
    'LICIPD.INVLINKED.LONGTERM.EQUITY.Q',
    'LICIPD.INVLINKED.LONGTERM.PREFERENCE.Q',
    'LICIPD.INVLINKED.LONGTERM.MUTUALFUND.Q',
    'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q',
    'LICIPD.INVLINKED.LONGTERM.OTHSECSBOND.Q',
    'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q',
    'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q',
    # -- Investments Linked Business SHORT TERM (9 fields)
    'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q',
    'LICIPD.INVLINKED.SHORTTERM.OTHAPPRSECS.Q',
    'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q',
    'LICIPD.INVLINKED.SHORTTERM.DEBENTBOND.Q',
    'LICIPD.INVLINKED.SHORTTERM.OTHSECSBOND.Q',
    'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q',
    'LICIPD.INVLINKED.SHORTTERM.OTHERNONAPPROVED.Q',
    'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q',
    'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q',
    # -- Revenue Account (10 fields)
    'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q',
    'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q',
    'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
    'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q',
    'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
    'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
    'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
    'LICIPD.REVENUEACCOUNT.NETINCOME.Q',
]

COLUMN_DESCRIPTIONS = [
    'Balance Sheet L-3 Shareholders',
    'Balance Sheet L-3 Policyholders',
    'Balance Sheet L-3 Asset Held to Cover Linked Liabilities',
    # -- Investments Policyholders LONG TERM
    'L-13 Long term investments Government securities and Government guaranteed bonds including Treasury Bills',
    'L-13 Long term investments Other Approved Securities',
    'L-13 Long term investments Equity',
    'L-13 Long term investments Preference',
    'L-13 Long term investments Mutual Funds',
    'L-13 Long term investments Debentures/ Bonds',
    'L-13 Long term investments Deposits with Social Security Fund',
    'L-13 Long term investments Other Securities and Bonds',
    'L-13 Long term investments Initial contribution to UTI II capital',
    'L-13 Long term investments Subsidiaries',
    'L-13 Long term investments Investment Properties-Real Estate',
    'L-13 Long term investments Investments in Infrastructure and Social Sector',
    'L-13 Long term investments Other than Approved Investments',
    'L-13 Long term investments Provision for Doubtful Investments',
    # -- Investments Policyholders SHORT TERM
    'L-13 Short term investments Government securities and Government guaranteed bonds including Treasury Bills',
    'L-13 Short term investments Other Approved Securities',
    'L-13 Short term investments Equity',
    'L-13 Short term investments Preference',
    'L-13 Short term investments Mutual Funds',
    'L-13 Short term investments Debentures/ Bonds',
    'L-13 Short term investments Other Securities',
    'L-13 Short term investments Investments in Infrastructure and Social Sector',
    'L-13 Short term investments Other than Approved Investments',
    'L-13 Short term investments Provision for Doubtful Investments',
    'L-13 Short term investments Total',
    # -- Investments Linked Business LONG TERM
    'L-14 Long term investments Government securities and Government guaranteed bonds including Treasury Bills',
    'L-14 Long term investments Other Approved Securities',
    'L-14 Long term investments Equity',
    'L-14 Long term investments Preference',
    'L-14 Long term investments Mutual Funds',
    'L-14 Long term investments Debentures/ Bonds',
    'L-14 Long term investments Other Securities',
    'L-14 Long term investments Investments in Infrastructure and Social Sector',
    'L-14 Long term investments Other than Approved Investments',
    # -- Investments Linked Business SHORT TERM
    'L-14 Short term investments Government securities and Government guaranteed bonds including Treasury Bills',
    'L-14 Short term investments Other Approved Securities',
    'L-14 Short term investments Mutual Funds',
    'L-14 Short term investments Debentures/ Bonds',
    'L-14 Short term investments Other Securities',
    'L-14 Short term investments Investments in Infrastructure and Social Sector',
    'L-14 Short term investments Other than Approved Investments',
    'L-14 Short term investments Other Current Assets (Net)',
    'L-14 Short term investments Total',
    # -- Revenue Account
    'Revenue Account L-1 Premiums earned \u2013 net (sum of Premium & Reinsurance ceded & Reinsurance accepted)',
    'Revenue Account L-1 Interest Dividends and Rent \u2013 Gross',
    'Revenue Account L-1 Investment Gain/Loss On Sale/Redemption (sum of Profit & Lose on sale/redemption of investments)',
    'Revenue Account L-1 Transfer/Gain on revaluation/change in fair value',
    'Revenue Account L-1 Other Income',
    'Revenue Account L-1 Total (A)',
    'Revenue Account L-1 Total (B)',
    'Revenue Account L-1 Benefits Paid (Net)',
    'Revenue Account L-1 Bonuses Paid',
    'Revenue Account L-1 Net Income ( it is the sum of TOTAL (A) TOTAL (B) Benefits Paid and Bonuses paid)',
]

# ── PDF Label -> Column Code Mapping ──────────────────────────────────────────
# Used by extractor to map PDF row labels to master CSV column codes.
# Labels are normalized (lowercased, stripped) before matching.

# Balance Sheet: label -> code
BALANCE_SHEET_LABELS = {
    'shareholders': 'LICIPD.BALANCESHEET.SHAREHOLDERS.Q',
    'policyholders': 'LICIPD.BALANCESHEET.POLICYHOLDERS.Q',
    'asset held to cover linked liabilities': 'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
    'assets held to cover linked liabilities': 'LICIPD.BALANCESHEET.ASSETSLINKEDLIABILITIES.Q',
}

# Investments Policyholders (L-13): section_context + label -> code
# section_context is "long_term" or "short_term"
INVPHS_LABELS = {
    ('long_term', 'government securities and government guaranteed bonds including treasury bills'): 'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q',
    ('long_term', 'govt. securities and govt. guaranteed bonds including treasury bills'): 'LICIPD.INVPHS.LONGTERM.GOVTSECS.Q',
    ('long_term', 'other approved securities'): 'LICIPD.INVPHS.LONGTERM.OTHAPPRSECS.Q',
    ('long_term', 'equity'): 'LICIPD.INVPHS.LONGTERM.EQUITY.Q',
    ('long_term', 'preference'): 'LICIPD.INVPHS.LONGTERM.PREFERENCE.Q',
    ('long_term', 'mutual funds'): 'LICIPD.INVPHS.LONGTERM.MUTUALFUND.Q',
    ('long_term', 'debentures/ bonds'): 'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'debentures/bonds'): 'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'debentures / bonds'): 'LICIPD.INVPHS.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'deposits with social security fund'): 'LICIPD.INVPHS.LONGTERM.DEPOSSSF.Q',
    ('long_term', 'other securities & bonds'): 'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q',
    ('long_term', 'other securities and bonds'): 'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q',
    ('long_term', 'other securities'): 'LICIPD.INVPHS.LONGTERM.OTHSECSBOND.Q',
    ('long_term', 'initial contribution to uti ii capital'): 'LICIPD.INVPHS.LONGTERM.CONTRUTI.Q',
    ('long_term', 'subsidiaries'): 'LICIPD.INVPHS.LONGTERM.SUBSIDIARIES.Q',
    ('long_term', 'investment properties-real estate'): 'LICIPD.INVPHS.LONGTERM.REALESTATE.Q',
    ('long_term', 'investment properties - real estate'): 'LICIPD.INVPHS.LONGTERM.REALESTATE.Q',
    ('long_term', 'investments in infrastructure and social sector'): 'LICIPD.INVPHS.LONGTERM.INFRASOCIALSECTOR.Q',
    ('long_term', 'other than approved investments'): 'LICIPD.INVPHS.LONGTERM.OTHERNONAPPROVED.Q',
    ('long_term', 'provision for doubtful investments'): 'LICIPD.INVPHS.LONGTERM.PROVISIONDOUBTFUL.Q',
    # SHORT TERM
    ('short_term', 'government securities and government guaranteed bonds including treasury bills'): 'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q',
    ('short_term', 'govt. securities and govt. guaranteed bonds including treasury bills'): 'LICIPD.INVPHS.SHORTTERM.GOVTSECS.Q',
    ('short_term', 'other approved securities'): 'LICIPD.INVPHS.SHORTTERM.OTHAPPRSECS.Q',
    ('short_term', 'equity'): 'LICIPD.INVPHS.SHORTTERM.EQUITY.Q',
    ('short_term', 'preference'): 'LICIPD.INVPHS.SHORTTERM.PREFERENCE.Q',
    ('short_term', 'mutual funds'): 'LICIPD.INVPHS.SHORTTERM.MUTUALFUND.Q',
    ('short_term', 'debentures/ bonds'): 'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'debentures/bonds'): 'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'debentures / bonds'): 'LICIPD.INVPHS.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'other securities'): 'LICIPD.INVPHS.SHORTTERM.OTHSECSBOND.Q',
    ('short_term', 'other securities & bonds'): 'LICIPD.INVPHS.SHORTTERM.OTHSECSBOND.Q',
    ('short_term', 'other securities and bonds'): 'LICIPD.INVPHS.SHORTTERM.OTHSECSBOND.Q',
    ('short_term', 'investments in infrastructure and social sector'): 'LICIPD.INVPHS.SHORTTERM.INFRASOCIALSECTOR.Q',
    ('short_term', 'other than approved investments'): 'LICIPD.INVPHS.SHORTTERM.OTHERNONAPPROVED.Q',
    ('short_term', 'provision for doubtful investments'): 'LICIPD.INVPHS.SHORTTERM.PROVISIONDOUBTFUL.Q',
    ('short_term', 'total'): 'LICIPD.INVPHS.SHORTTERM.TOTAL.Q',
}

# Investments Linked Business (L-14): section_context + label -> code
INVLINKED_LABELS = {
    ('long_term', 'government securities and government guaranteed bonds including treasury bills'): 'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q',
    ('long_term', 'govt. securities and govt. guaranteed bonds including treasury bills'): 'LICIPD.INVLINKED.LONGTERM.GOVTSECS.Q',
    ('long_term', 'other approved securities'): 'LICIPD.INVLINKED.LONGTERM.OTHAPPRSECS.Q',
    ('long_term', 'equity'): 'LICIPD.INVLINKED.LONGTERM.EQUITY.Q',
    ('long_term', 'preference'): 'LICIPD.INVLINKED.LONGTERM.PREFERENCE.Q',
    ('long_term', 'mutual funds'): 'LICIPD.INVLINKED.LONGTERM.MUTUALFUND.Q',
    ('long_term', 'debentures/ bonds'): 'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'debentures/bonds'): 'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'debentures / bonds'): 'LICIPD.INVLINKED.LONGTERM.DEBENTBOND.Q',
    ('long_term', 'other securities'): 'LICIPD.INVLINKED.LONGTERM.OTHSECSBOND.Q',
    ('long_term', 'other securities (to be specified)'): 'LICIPD.INVLINKED.LONGTERM.OTHSECSBOND.Q',
    ('long_term', 'investments in infrastructure and social sector'): 'LICIPD.INVLINKED.LONGTERM.INFRASOCIALSECTOR.Q',
    ('long_term', 'other than approved investments'): 'LICIPD.INVLINKED.LONGTERM.OTHERNONAPPROVED.Q',
    # SHORT TERM
    ('short_term', 'government securities and government guaranteed bonds including treasury bills'): 'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q',
    ('short_term', 'govt. securities and govt. guaranteed bonds including treasury bills'): 'LICIPD.INVLINKED.SHORTTERM.GOVTSECS.Q',
    ('short_term', 'other approved securities'): 'LICIPD.INVLINKED.SHORTTERM.OTHAPPRSECS.Q',
    ('short_term', 'mutual funds'): 'LICIPD.INVLINKED.SHORTTERM.MUTUALFUND.Q',
    ('short_term', 'debentures/ bonds'): 'LICIPD.INVLINKED.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'debentures/bonds'): 'LICIPD.INVLINKED.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'debentures / bonds'): 'LICIPD.INVLINKED.SHORTTERM.DEBENTBOND.Q',
    ('short_term', 'other securities'): 'LICIPD.INVLINKED.SHORTTERM.OTHSECSBOND.Q',
    ('short_term', 'investments in infrastructure and social sector'): 'LICIPD.INVLINKED.SHORTTERM.INFRASOCIALSECTOR.Q',
    ('short_term', 'other than approved investments'): 'LICIPD.INVLINKED.SHORTTERM.OTHERNONAPPROVED.Q',
    ('short_term', 'other current assets (net)'): 'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q',
    ('short_term', 'other current assets'): 'LICIPD.INVLINKED.SHORTTERM.NETCURRASST.Q',
    ('short_term', 'total'): 'LICIPD.INVLINKED.SHORTTERM.TOTAL.Q',
}

# Revenue Account (L-1A / L-1): label -> code or "component" marker
# Components are used to calculate derived fields
REVENUE_LABELS = {
    'premium': '_COMPONENT_PREMIUM',
    'premiums': '_COMPONENT_PREMIUM',
    'reinsurance ceded': '_COMPONENT_REINS_CEDED',
    'reinsurance accepted': '_COMPONENT_REINS_ACCEPTED',
    'interest, dividends & rent - gross': 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    'interest, dividends and rent - gross': 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    'interest, dividends & rent \u2013 gross': 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    'interest dividends and rent gross': 'LICIPD.REVENUEACCOUNT.INTDIVINCOME.Q',
    'profit on sale/redemption of investments': '_COMPONENT_PROFIT_SALE',
    'profit on sale / redemption of investments': '_COMPONENT_PROFIT_SALE',
    '(loss on sale/redemption of investments)': '_COMPONENT_LOSS_SALE',
    '(loss on sale/ redemption of investments)': '_COMPONENT_LOSS_SALE',
    'loss on sale/redemption of investments': '_COMPONENT_LOSS_SALE',
    'loss on sale/ redemption of investments': '_COMPONENT_LOSS_SALE',
    'transfer/gain on revaluation/change in fair value': 'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
    'transfer/gain on revaluation/change in fair value*': 'LICIPD.REVENUEACCOUNT.INVGAINLOSSREVAL.Q',
    'other income': 'LICIPD.REVENUEACCOUNT.OTHERINCOME.Q',
    'total (a)': 'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
    'total (b)': 'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
    'benefits paid (net)': 'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'benefits paid(net)': 'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
    'bonuses paid': 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
    'interim bonuses paid': 'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
}

# Calculated fields from Revenue Account components
REVENUE_CALCULATED = {
    'LICIPD.REVENUEACCOUNT.PREMIUMSNET.Q': {
        'components': ['_COMPONENT_PREMIUM', '_COMPONENT_REINS_CEDED', '_COMPONENT_REINS_ACCEPTED'],
        'formula': 'sum',  # a + b + c (b is typically negative from parentheses)
    },
    'LICIPD.REVENUEACCOUNT.INVGAINLOSSSALE.Q': {
        'components': ['_COMPONENT_PROFIT_SALE', '_COMPONENT_LOSS_SALE'],
        'formula': 'sum',  # a + b (b is typically negative from parentheses)
    },
    'LICIPD.REVENUEACCOUNT.NETINCOME.Q': {
        'components': [
            'LICIPD.REVENUEACCOUNT.TOTALINCOME.Q',
            'LICIPD.REVENUEACCOUNT.OPERATINGEXP.Q',
            'LICIPD.REVENUEACCOUNT.BENEFITSPAID.Q',
            'LICIPD.REVENUEACCOUNT.BONUSESPAID.Q',
        ],
        'formula': 'sum',  # TOTAL(A) + TOTAL(B) + Benefits Paid + Bonuses Paid
    },
}

# ── Quarter Label Mapping ─────────────────────────────────────────────────────
# Calendar year based: Q1=Mar, Q2=Jun, Q3=Sep, Q4=Dec
MONTH_TO_QUARTER = {
    3: 'Q1',   # March 31 -> Q1
    6: 'Q2',   # June 30 -> Q2
    9: 'Q3',   # September 30 -> Q3
    12: 'Q4',  # December 31 -> Q4
}

# ── META File Template ────────────────────────────────────────────────────────
META_TEMPLATE = {
    'FREQUENCY': 'Q',
    'MULTIPLIER': 5,
    'AGGREGATION_TYPE': 'END_OF_PERIOD',
    'UNIT_TYPE': 'FLOW',
    'DATA_TYPE': 'CURRENCY',
    'DATA_UNIT': 'INR',
    'SEASONALLY_ADJUSTED': 'NSA',
    'ANNUALIZED': False,
    'STATE': 'ACTIVE',
    'PROVIDER_MEASURE_URL': 'https://www.licindia.in/Bottom-Links/Public-disclosure',
    'PROVIDER': 'AfricaAI',
    'SOURCE': 'LIC',
    'SOURCE_DESCRIPTION': 'Life Insurance Corporation of India',
    'COUNTRY': 'IND',
    'DATASET': 'LICIPD',
}
