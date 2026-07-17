"""
Scraper for LIC India Public Disclosure PDFs.

3-level navigation:
  Level 1: Public Disclosure main page  -> pick year (latest or TARGET_YEAR)
  Level 2: Year page                    -> pick date (latest or TARGET_DATE)
  Level 3: Date page                    -> find and download 4 PDF categories

Downloads via requests using browser session cookies (faster than browser trigger).

Returns:
    {
        'balance_sheet':               [abs_path, ...],
        'investments_policyholders':   [abs_path, ...],
        'investments_linked':          [abs_path, ...],
        'revenue_account':             [abs_path, ...],  # up to 2 PDFs
        'quarter':                     '2026-Q1',
        'run_dir':                     '/abs/path/downloads/20260528_120000/',
    }
"""

import os
import re
import sys
import json
import time
import random
import logging
import subprocess
import urllib.parse
from datetime import datetime

import requests
import urllib3

import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_SITE = 'https://www.licindia.in'

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _human_delay(lo=0.8, hi=2.2):
    time.sleep(random.uniform(lo, hi))


def get_chrome_version():
    """Detect installed Chrome major version. Works on Windows and Linux."""
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Google\Chrome\BLBeacon',
            )
            return int(winreg.QueryValueEx(key, 'version')[0].split('.')[0])
        except Exception:
            pass
    for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']:
        try:
            out = subprocess.check_output(
                [cmd, '--version'], stderr=subprocess.DEVNULL
            ).decode()
            return int(out.strip().split()[-1].split('.')[0])
        except Exception:
            continue
    return None


def _build_driver(download_dir):
    """Create an undetected Chrome driver with stealth and download prefs."""
    import undetected_chromedriver as uc
    from selenium_stealth import stealth

    opts = uc.ChromeOptions()
    if config.HEADLESS_MODE:
        opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--lang=en-US,en;q=0.9')
    opts.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'plugins.always_open_pdf_externally': True,
        'safebrowsing.enabled': True,
    })

    version = get_chrome_version()
    kwargs = {'options': opts, 'use_subprocess': True}
    if version:
        kwargs['version_main'] = version

    driver = uc.Chrome(**kwargs)

    stealth(
        driver,
        languages=['en-US', 'en'],
        vendor='Google Inc.',
        platform='Win32',
        webgl_vendor='Intel Inc.',
        renderer='Intel Iris OpenGL Engine',
        fix_hairline=True,
    )

    # Allow headless downloads via CDP
    driver.execute_cdp_cmd(
        'Page.setDownloadBehavior',
        {'behavior': 'allow', 'downloadPath': download_dir},
    )
    return driver


def _download_pdf_via_requests(url, dest_path, cookies=None):
    """Download a PDF from url to dest_path using requests. Returns True on success."""
    try:
        resp = requests.get(
            url,
            headers=_HEADERS,
            cookies=cookies or {},
            stream=True,
            timeout=120,
            verify=False,
        )
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'html' in content_type and 'pdf' not in content_type:
            logger.warning(f"Response is HTML not PDF ({content_type}) for {url}")
            return False

        with open(dest_path, 'wb') as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

        size = os.path.getsize(dest_path)
        if size < 10_000:
            logger.warning(f"Suspiciously small download: {size} bytes at {dest_path}")
            return False

        logger.info(f"Downloaded {size:,} bytes -> {dest_path}")
        return True
    except Exception as exc:
        logger.warning(f"requests download failed for {url}: {exc}")
        return False


# ── Level 1: Year selection ──────────────────────────────────────────────────

def _get_year_links(driver):
    """
    Find year links in <section id="maincontent"> on the Public Disclosure page.
    Returns list of (text, full_href) in page order (latest year listed first).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    WebDriverWait(driver, config.WAIT_TIMEOUT).until(
        EC.presence_of_element_located((By.ID, 'maincontent'))
    )
    _human_delay(1.0, 2.0)

    section = driver.find_element(By.ID, 'maincontent')
    links = section.find_elements(By.TAG_NAME, 'a')

    year_links = []
    for link in links:
        href = link.get_attribute('href') or ''
        text = link.text.strip()
        # Year links contain "public-disclosure" or a YYYY-YY / YYYY-YYYY pattern
        if 'public-disclosure' in href or re.search(r'\d{4}[-–]\d{2,4}', href):
            year_links.append((text, href))

    logger.info(f"Found {len(year_links)} year links")
    return year_links


def _select_year(year_links):
    """
    Pick the year to navigate to.
    TARGET_YEAR = None  -> first in list (latest).
    TARGET_YEAR = str   -> match by text content.
    """
    if not year_links:
        raise RuntimeError("No year links found on Public Disclosure page")

    if config.TARGET_YEAR is None:
        logger.info(f"Auto-selecting latest year: {year_links[0][0]}")
        return year_links[0]

    target = config.TARGET_YEAR.lower().replace(' ', '')
    for text, href in year_links:
        if target in text.lower().replace(' ', ''):
            logger.info(f"Matched TARGET_YEAR: {text}")
            return text, href

    logger.warning(f"TARGET_YEAR '{config.TARGET_YEAR}' not found; using latest")
    return year_links[0]


# ── Level 2: Date selection ──────────────────────────────────────────────────

def _get_date_links(driver):
    """
    Find quarterly date links in <section id="maincontent"> on a year page.
    Returns list of (text, full_href) in page order (oldest -> newest).
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    WebDriverWait(driver, config.WAIT_TIMEOUT).until(
        EC.presence_of_element_located((By.ID, 'maincontent'))
    )
    _human_delay(1.0, 2.0)

    section = driver.find_element(By.ID, 'maincontent')
    links = section.find_elements(By.TAG_NAME, 'a')

    date_links = []
    for link in links:
        href = link.get_attribute('href') or ''
        text = link.text.strip()
        # Date links contain "as-at-" in href, or "as at" in text
        if 'as-at-' in href.lower() or 'as at' in text.lower():
            date_links.append((text, href))

    logger.info(f"Found {len(date_links)} date links")
    return date_links


def _parse_quarter_from_date(date_text, date_href=''):
    """
    Derive YYYY-QN from a date-link text like "As at March 31, 2026"
    or href like "/web/guest/as-at-march-31-2026".
    Returns "YYYY-QN" or None.
    """
    month_map = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12,
    }

    for src in [date_text.lower(), date_href.lower()]:
        for month_name, month_num in month_map.items():
            if month_name in src:
                year_match = re.search(r'\b(20\d{2})\b', src)
                if year_match:
                    year = int(year_match.group(1))
                    q = config.MONTH_TO_QUARTER.get(month_num)
                    if q:
                        return f"{year}-{q}"
    return None


# ── Level 3: PDF discovery ───────────────────────────────────────────────────

def _get_all_pdf_links(driver):
    """
    Extract all (title, full_href) for PDF links in the report table on a date page.
    Strips file-size annotations from title text.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    WebDriverWait(driver, config.WAIT_TIMEOUT).until(
        EC.presence_of_element_located((By.ID, 'maincontent'))
    )
    _human_delay(1.5, 2.5)

    links = driver.find_elements(
        By.XPATH, "//section[@id='maincontent']//a[contains(@href, '.pdf')]"
    )

    pdf_links = []
    for link in links:
        href = link.get_attribute('href') or ''
        if not href.startswith('http'):
            href = _BASE_SITE + href
        title = link.text.strip()
        # Remove embedded "(280 KB)" size labels
        title = re.sub(r'\s*\(\s*[\d.,]+\s*[KMG]B\s*\)', '', title).strip()
        if title and '.pdf' in href.lower():
            pdf_links.append((title, href))

    logger.info(f"Found {len(pdf_links)} PDF links")
    return pdf_links


def _filename_from_href(href):
    """
    Extract a human-readable filename from a LIC PDF href.
    href form: .../L-13-+Investments+...31.03.2026.pdf/uuid?t=...
    Returns decoded filename string including .pdf extension.
    """
    path = href.split('?')[0].rstrip('/')
    for part in reversed(path.split('/')):
        if part.lower().endswith('.pdf'):
            return urllib.parse.unquote_plus(part)
    # Fallback: use last path segment + .pdf
    last = path.split('/')[-1]
    name = urllib.parse.unquote_plus(last)
    return name if name.lower().endswith('.pdf') else name + '.pdf'


# ── PDF category matchers ─────────────────────────────────────────────────────

def _match_balance_sheet(pdf_links):
    """L-3 or L-3A Balance Sheet. Returns (title, href) or None."""
    for title, href in pdf_links:
        t = title.strip()
        # L-3 or L-3A followed by separator, but not L-30, L-31, etc.
        if re.match(r'L-3[A-Z]?[-\s–]', t) and 'balance sheet' in t.lower():
            logger.info(f"  Balance Sheet: {t}")
            return title, href
    logger.warning("  Balance Sheet: no match found")
    return None


def _match_investments_policyholders(pdf_links):
    """L-13 Investments Policyholders. Returns (title, href) or None."""
    for title, href in pdf_links:
        t = title.strip()
        if t.startswith('L-13') and 'investment' in t.lower():
            logger.info(f"  Investments PH: {t}")
            return title, href
    logger.warning("  Investments PH: no match found")
    return None


def _match_investments_linked(pdf_links):
    """L-14 Investments Linked (not L-14A). Returns (title, href) or None."""
    for title, href in pdf_links:
        t = title.strip()
        if not t.startswith('L-14'):
            continue
        # Exclude L-14A (Additional Information)
        if re.match(r'L-14\s*A\b', t, re.IGNORECASE):
            continue
        if any(kw in t.lower() for kw in ['investment', 'linked', 'assets held']):
            logger.info(f"  Investments Linked: {t}")
            return title, href
    logger.warning("  Investments Linked: no match found")
    return None


def _match_revenue_accounts(pdf_links):
    """
    Find Revenue Account PDFs matching highest-priority keyword.
    Returns list of (title, href) — typically 2 PDFs (current + prior year companion).
    """
    for priority_kw in config.REVENUE_ACCOUNT_PRIORITY:
        matches = [
            (title, href) for title, href in pdf_links
            if 'revenue account' in title.lower()
            and priority_kw.lower() in title.lower()
        ]
        if matches:
            logger.info(f"  Revenue Account ({priority_kw!r}): {len(matches)} PDFs")
            return matches

    # Last resort: any Revenue Account link
    matches = [(t, h) for t, h in pdf_links if 'revenue account' in t.lower()]
    if matches:
        logger.info(f"  Revenue Account (fallback): {len(matches)} PDFs")
    else:
        logger.warning("  Revenue Account: no match found")
    return matches


def _has_core_pdfs(pdf_links):
    """True if the date page has at least Balance Sheet + Investments PH PDFs."""
    return (
        _match_balance_sheet(pdf_links) is not None
        and _match_investments_policyholders(pdf_links) is not None
    )


# ── Download helper ──────────────────────────────────────────────────────────

def _download_pdf(url, cat_dir, filename, cookies):
    """Download url to cat_dir/filename. Returns abs path or None."""
    os.makedirs(cat_dir, exist_ok=True)
    dest = os.path.join(cat_dir, filename)
    if _download_pdf_via_requests(url, dest, cookies):
        return dest
    return None


# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state():
    """Load state.json, returning an empty dict if the file doesn't exist yet."""
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def _quarter_already_processed(quarter):
    """Return True if quarter appears in state.json processed_quarters."""
    state = _load_state()
    return quarter in state.get('processed_quarters', {})


# ── Public entry point ────────────────────────────────────────────────────────

def download():
    """
    Navigate LIC India Public Disclosure and download all 4 PDF categories.

    Returns dict with keys:
        balance_sheet, investments_policyholders, investments_linked,
        revenue_account  -> each a list of abs paths
        quarter          -> "YYYY-QN" or None
        run_dir          -> abs path of the download folder for this run
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(config.DOWNLOAD_DIR, timestamp)
    os.makedirs(run_dir, exist_ok=True)

    result = {
        'balance_sheet': [],
        'investments_policyholders': [],
        'investments_linked': [],
        'revenue_account': [],
        'quarter':    None,
        'date_text':  None,
        'skipped':    False,
        'run_dir':    run_dir,
    }

    driver = None
    try:
        driver = _build_driver(run_dir)

        # ── Level 1: Public Disclosure main page → year ─────────────────
        logger.info(f"Navigating to {config.BASE_URL}")
        driver.get(config.BASE_URL)
        _human_delay(2.0, 3.5)

        year_links = _get_year_links(driver)
        year_text, year_href = _select_year(year_links)

        logger.info(f"Year selected: {year_text!r}")
        driver.get(year_href)
        _human_delay(2.0, 3.0)

        # ── Level 2: Year/date search with cross-year fallback ──────────
        # year_links is ordered latest-first; year_start_idx is the index of
        # the selected year. When TARGET_YEAR is None, we walk forward through
        # older years until we find one with core PDFs posted.
        year_start_idx = next(
            (i for i, (t, _) in enumerate(year_links) if t == year_text),
            0,
        )

        pdf_links = []
        date_text = date_href = None
        found_core = False

        for yi, (cur_year_text, cur_year_href) in enumerate(year_links[year_start_idx:]):
            if yi > 0:
                logger.info(f"Falling back to previous year: {cur_year_text!r}")
                driver.get(cur_year_href)
                _human_delay(2.0, 3.0)

            date_links = _get_date_links(driver)
            if not date_links:
                logger.warning(f"No date links found for year {cur_year_text!r}")
                continue

            # Determine starting date index
            if config.TARGET_DATE is not None and yi == 0:
                target = config.TARGET_DATE.lower().replace(' ', '')
                start_idx = len(date_links) - 1
                for i, (text, href) in enumerate(date_links):
                    if target in text.lower().replace(' ', ''):
                        start_idx = i
                        break
            else:
                start_idx = len(date_links) - 1   # latest = last in list

            chosen_idx = start_idx
            for idx in range(start_idx, -1, -1):
                dt, dh = date_links[idx]
                logger.info(f"Navigating to date: {dt!r}")
                driver.get(dh)
                _human_delay(2.0, 3.0)

                try:
                    page_pdf_links = _get_all_pdf_links(driver)
                except Exception as exc:
                    logger.warning(f"Timeout loading PDF list at {dt!r}: {exc}; retrying")
                    _human_delay(3.0, 5.0)
                    driver.refresh()
                    _human_delay(3.0, 5.0)
                    try:
                        page_pdf_links = _get_all_pdf_links(driver)
                    except Exception:
                        logger.warning(f"Retry also failed for {dt!r}; skipping this date")
                        page_pdf_links = []

                if _has_core_pdfs(page_pdf_links):
                    chosen_idx = idx
                    pdf_links = page_pdf_links
                    found_core = True
                    logger.info(f"PDFs confirmed available at: {dt!r}")
                    break

                if config.TARGET_DATE is not None and yi == 0:
                    logger.warning(f"Core PDFs not found at {dt!r} (TARGET_DATE set)")
                    pdf_links = page_pdf_links
                    break

                logger.warning(f"Core PDFs not yet posted at {dt!r}; trying previous date")
                pdf_links = page_pdf_links

            if date_links:
                date_text, date_href = date_links[chosen_idx]

            if found_core:
                break

            # Don't cross year boundaries when a target year or date is pinned
            if config.TARGET_YEAR is not None or config.TARGET_DATE is not None:
                break

            logger.info(f"No core PDFs in year {cur_year_text!r}; trying previous year")

        if not pdf_links:
            raise RuntimeError("No PDF links found on any date page")

        quarter = _parse_quarter_from_date(date_text or '', date_href or '')
        result['quarter']   = quarter
        result['date_text'] = date_text
        logger.info(f"Quarter: {quarter}")

        # ── Already-processed check ──────────────────────────────────────
        if quarter and config.SKIP_IF_PROCESSED and _quarter_already_processed(quarter):
            entry    = _load_state().get('processed_quarters', {}).get(quarter, {})
            last_run = entry.get('processed_at', 'unknown') if isinstance(entry, dict) else str(entry)
            logger.info(
                f"NO NEW DATA — {quarter} ({date_text}) was already processed on {last_run}. "
                f"Set SKIP_IF_PROCESSED=False in config.py to bypass."
            )
            result['skipped'] = True
            return result

        if quarter:
            logger.info(f"NEW DATA — {quarter} ({date_text}) has not been processed before")

        # Snapshot session cookies once for all requests downloads
        cookies = {c['name']: c['value'] for c in driver.get_cookies()}

        # ── Level 3: Download each category ─────────────────────────────
        logger.info("=== Downloading PDFs ===")

        bs = _match_balance_sheet(pdf_links)
        if bs:
            fname = _filename_from_href(bs[1])
            path = _download_pdf(bs[1], os.path.join(run_dir, 'balance_sheet'), fname, cookies)
            if path:
                result['balance_sheet'].append(path)

        invph = _match_investments_policyholders(pdf_links)
        if invph:
            fname = _filename_from_href(invph[1])
            path = _download_pdf(invph[1], os.path.join(run_dir, 'investments_policyholders'), fname, cookies)
            if path:
                result['investments_policyholders'].append(path)

        invlnk = _match_investments_linked(pdf_links)
        if invlnk:
            fname = _filename_from_href(invlnk[1])
            path = _download_pdf(invlnk[1], os.path.join(run_dir, 'investments_linked'), fname, cookies)
            if path:
                result['investments_linked'].append(path)

        rev_matches = _match_revenue_accounts(pdf_links)
        cat_dir_rev = os.path.join(run_dir, 'revenue_account')
        for title, href in rev_matches:
            fname = _filename_from_href(href)
            path = _download_pdf(href, cat_dir_rev, fname, cookies)
            if path:
                result['revenue_account'].append(path)

        total = sum(len(v) for k, v in result.items() if isinstance(v, list))
        logger.info(
            f"Scraper complete: {total} PDFs downloaded to {run_dir}  "
            f"[quarter={quarter}]"
        )

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return result


# ── Backfill helpers ──────────────────────────────────────────────────────────

def _discover_all_available(driver, stop_after=None):
    """
    Walk year pages on LIC site and collect (quarter, date_text, date_href).
    Parses quarter labels from date link text — does NOT navigate to date pages.
    Returns list sorted oldest → newest.

    stop_after: quarter string (e.g. '2025-Q2'). Year pages are scanned
    newest-first; once an entire year's quarters all fall at or before
    stop_after we know older years are irrelevant and scanning stops early.
    """
    logger.info(f"Discovery: navigating to {config.BASE_URL}")
    driver.get(config.BASE_URL)
    _human_delay(2.0, 3.5)

    year_links = _get_year_links(driver)
    all_quarters = []
    seen = set()

    for year_text, year_href in year_links:
        logger.info(f"Discovery: scanning {year_text!r}")
        driver.get(year_href)
        _human_delay(1.5, 2.5)

        year_quarters = []
        for date_text, date_href in _get_date_links(driver):
            q = _parse_quarter_from_date(date_text, date_href)
            if q and q not in seen:
                seen.add(q)
                all_quarters.append((q, date_text, date_href))
                year_quarters.append(q)

        # Early stop: every quarter in this year is at or before our floor,
        # so all older year pages are guaranteed to be irrelevant too.
        if stop_after and year_quarters and max(year_quarters) <= stop_after:
            logger.info(
                f"Discovery: earliest needed quarter reached after {year_text!r}; "
                f"stopping early"
            )
            break

    all_quarters.sort(key=lambda x: x[0])
    logger.info(
        f"Discovery complete: {len(all_quarters)} quarters found, "
        f"{len([q for q in all_quarters if stop_after is None or q[0] > stop_after])} new"
    )
    return all_quarters


def _download_quarter(driver, quarter, date_text, date_href, base_run_dir):
    """
    Navigate to a specific date page and download all 4 PDF categories.
    Returns a pdf_paths dict in the same format as download().
    Caller owns the driver lifecycle.
    """
    quarter_dir = os.path.join(base_run_dir, quarter.replace('-', '_'))
    os.makedirs(quarter_dir, exist_ok=True)

    result = {
        'balance_sheet':             [],
        'investments_policyholders': [],
        'investments_linked':        [],
        'revenue_account':           [],
        'quarter':   quarter,
        'date_text': date_text,
        'skipped':   False,
        'run_dir':   quarter_dir,
    }

    logger.info(f"[{quarter}] Navigating to {date_text!r}")
    driver.get(date_href)
    _human_delay(2.0, 3.0)

    try:
        pdf_links = _get_all_pdf_links(driver)
    except Exception as exc:
        logger.warning(f"[{quarter}] Page load timeout ({exc}); retrying")
        _human_delay(3.0, 5.0)
        driver.refresh()
        _human_delay(3.0, 5.0)
        try:
            pdf_links = _get_all_pdf_links(driver)
        except Exception:
            logger.error(f"[{quarter}] Retry failed; skipping this quarter")
            return result

    if not _has_core_pdfs(pdf_links):
        logger.warning(f"[{quarter}] Core PDFs not yet available; skipping")
        return result

    cookies = {c['name']: c['value'] for c in driver.get_cookies()}

    bs = _match_balance_sheet(pdf_links)
    if bs:
        path = _download_pdf(
            bs[1], os.path.join(quarter_dir, 'balance_sheet'),
            _filename_from_href(bs[1]), cookies,
        )
        if path:
            result['balance_sheet'].append(path)

    invph = _match_investments_policyholders(pdf_links)
    if invph:
        path = _download_pdf(
            invph[1], os.path.join(quarter_dir, 'investments_policyholders'),
            _filename_from_href(invph[1]), cookies,
        )
        if path:
            result['investments_policyholders'].append(path)

    invlnk = _match_investments_linked(pdf_links)
    if invlnk:
        path = _download_pdf(
            invlnk[1], os.path.join(quarter_dir, 'investments_linked'),
            _filename_from_href(invlnk[1]), cookies,
        )
        if path:
            result['investments_linked'].append(path)

    for _, href in _match_revenue_accounts(pdf_links):
        path = _download_pdf(
            href, os.path.join(quarter_dir, 'revenue_account'),
            _filename_from_href(href), cookies,
        )
        if path:
            result['revenue_account'].append(path)

    total = sum(len(v) for k, v in result.items() if isinstance(v, list))
    logger.info(f"[{quarter}] Downloaded {total} PDFs to {quarter_dir}")
    return result


def discover_and_download(existing_quarters, base_run_dir, max_quarters=None):
    """
    Single browser session: discover all quarters available on LIC site,
    filter out existing_quarters, then download PDFs for the gaps.

    Args:
        existing_quarters : set/list of quarter strings already in master CSV
        base_run_dir      : directory under which per-quarter subdirs are created
        max_quarters      : None = all missing; N = only the N most-recent missing

    Returns:
        list of pdf_paths dicts (oldest → newest), empty if no gaps found
    """
    existing = set(existing_quarters)
    last = max(existing) if existing else None
    driver = None
    try:
        driver = _build_driver(base_run_dir)

        available = _discover_all_available(driver, stop_after=last)

        # Only consider quarters that come after the last entry already in the
        # master CSV — backfill picks up forward from where we stopped, never back.
        missing = [
            (q, dt, dh) for q, dt, dh in available
            if q not in existing and (last is None or q > last)
        ]

        if not missing:
            logger.info("No missing quarters found — master CSV is up to date")
            return []

        if max_quarters is not None:
            missing = missing[-max_quarters:]   # keep only N most recent

        logger.info(
            f"Quarters to process ({len(missing)}): {[m[0] for m in missing]}"
        )

        results = []
        for quarter, date_text, date_href in missing:
            pdf_paths = _download_quarter(driver, quarter, date_text, date_href, base_run_dir)
            results.append(pdf_paths)

        return results

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
