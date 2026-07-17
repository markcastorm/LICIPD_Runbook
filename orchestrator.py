"""
Pipeline orchestrator for LICIPD data extraction.

Auto-backfill flow (BACKFILL_ENABLED = True, default):
  1. Read master CSV → determine which quarters are already present
  2. scraper.discover_and_download() → single browser session discovers every
     quarter available on LIC site, downloads PDFs only for the missing ones
  3. ThreadPoolExecutor → parallel PDF extraction across missing quarters
  4. Sequential file_generator.generate() calls in chronological order

Single-quarter flow (BACKFILL_ENABLED = False):
  Same as above but capped at the 1 most-recent missing quarter.
"""

import csv
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import config
import extractor
import file_generator
import scraper

logger = logging.getLogger(__name__)

_CATS = (
    'balance_sheet',
    'investments_policyholders',
    'investments_linked',
    'revenue_account',
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_master_quarters():
    """Return set of quarter labels already present in the master CSV."""
    if not os.path.exists(config.MASTER_CSV):
        return set()
    quarters = set()
    try:
        with open(config.MASTER_CSV, newline='', encoding='utf-8-sig') as fh:
            for i, row in enumerate(csv.reader(fh)):
                if i >= 2 and row and row[0].strip():
                    quarters.add(row[0].strip())
    except Exception as exc:
        logger.warning(f"Could not read master CSV: {exc}")
    return quarters


def _save_processed_state(quarter, date_text):
    """Record a successfully processed quarter in state.json."""
    try:
        state = {}
        if os.path.exists(config.STATE_FILE):
            try:
                with open(config.STATE_FILE, encoding='utf-8') as fh:
                    state = json.load(fh)
            except Exception:
                pass

        state.setdefault('processed_quarters', {})[quarter] = {
            'date_text':    date_text or '',
            'processed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        with open(config.STATE_FILE, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, indent=2)

        logger.info(f"State updated: {quarter} recorded in {config.STATE_FILE}")
    except Exception as exc:
        logger.warning(f"Could not update state file: {exc}")


# ── Pipeline entry point ──────────────────────────────────────────────────────

def main():
    """
    Run the full LICIPD pipeline.

    Returns dict:
        success    : bool
        skipped    : bool  (True when master CSV already has all available quarters)
        quarter    : most recently processed quarter string, or None
        quarters   : list of all quarter strings processed this run
        appended   : bool  (True if at least one CSV row was written)
        data_xlsx  : path of last-generated DATA xlsx, or None
        meta_xlsx  : path of last-generated META xlsx, or None
        zip        : path of last-generated ZIP, or None
        run_dir    : path to this run's download folder
        errors     : list of warning/error strings
    """
    summary = {
        'success':   False,
        'skipped':   False,
        'quarter':   None,
        'quarters':  [],
        'appended':  False,
        'data_xlsx': None,
        'meta_xlsx': None,
        'zip':       None,
        'run_dir':   None,
        'errors':    [],
    }

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(config.DOWNLOAD_DIR, timestamp)
    os.makedirs(run_dir, exist_ok=True)
    summary['run_dir'] = run_dir

    # ── Stage 1: Gap detection + download ────────────────────────────────────
    logger.info("=== Stage 1: Scraper ===")

    existing_quarters = _get_master_quarters()
    logger.info(
        f"Master CSV: {len(existing_quarters)} existing quarter(s) — "
        f"backfill={'ON' if config.BACKFILL_ENABLED else 'OFF'}"
    )

    max_q = None if config.BACKFILL_ENABLED else 1

    try:
        all_pdf_paths = scraper.discover_and_download(
            existing_quarters, run_dir, max_quarters=max_q,
        )
    except Exception as exc:
        msg = f"Scraper failed: {exc}"
        logger.error(msg, exc_info=True)
        summary['errors'].append(msg)
        return summary

    if not all_pdf_paths:
        summary['skipped'] = True
        summary['success'] = True
        logger.info("Pipeline: NO NEW DATA — master CSV is up to date")
        return summary

    # Partition into quarters with PDFs vs those that had nothing posted yet
    valid_pdf_paths = []
    for p in all_pdf_paths:
        q = p.get('quarter', '?')
        if any(p.get(cat) for cat in _CATS):
            valid_pdf_paths.append(p)
        else:
            missing_cats = [c for c in _CATS if not p.get(c)]
            msg = f"[{q}] No PDFs downloaded (categories missing: {missing_cats})"
            logger.warning(msg)
            summary['errors'].append(msg)

    if not valid_pdf_paths:
        msg = "Scraper returned no PDFs for any quarter"
        logger.error(msg)
        summary['errors'].append(msg)
        return summary

    logger.info(f"Scraper: {len(valid_pdf_paths)} quarter(s) with PDFs ready")

    # ── Stage 2: Parallel extraction ─────────────────────────────────────────
    n_workers = min(config.BACKFILL_MAX_WORKERS, len(valid_pdf_paths))
    logger.info(
        f"=== Stage 2: Extractor "
        f"({len(valid_pdf_paths)} quarter(s), {n_workers} worker(s)) ==="
    )

    # quarter_str -> (quarter_str, data_dict, date_text)
    quarter_results = {}

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(extractor.extract, pdf_paths): pdf_paths
            for pdf_paths in valid_pdf_paths
        }
        for future in as_completed(futures):
            src = futures[future]
            scraper_quarter = src.get('quarter', '?')
            try:
                q, data = future.result()
                effective_q = q or scraper_quarter
                if not effective_q:
                    msg = f"[{scraper_quarter}] Quarter label could not be determined"
                    logger.warning(msg)
                    summary['errors'].append(msg)
                    continue
                na_count = sum(1 for v in data.values() if v == 'NA')
                logger.info(
                    f"[{effective_q}] Extraction done  NA={na_count}/56"
                )
                quarter_results[effective_q] = (
                    effective_q, data, src.get('date_text'),
                )
            except Exception as exc:
                msg = f"[{scraper_quarter}] Extraction failed: {exc}"
                logger.error(msg, exc_info=True)
                summary['errors'].append(msg)

    if not quarter_results:
        msg = "All extractions failed"
        logger.error(msg)
        summary['errors'].append(msg)
        return summary

    # ── Stage 3: Sequential file generation (chronological order) ────────────
    logger.info(
        f"=== Stage 3: File Generator ({len(quarter_results)} quarter(s)) ==="
    )

    last_gen = None
    for q in sorted(quarter_results.keys()):
        effective_q, data, date_text = quarter_results[q]
        try:
            gen_result = file_generator.generate(effective_q, data)
            _save_processed_state(effective_q, date_text)
            summary['quarters'].append(effective_q)
            summary['appended'] = summary['appended'] or gen_result.get('appended', False)
            last_gen = gen_result
            logger.info(f"[{effective_q}] Outputs generated")
        except Exception as exc:
            msg = f"[{effective_q}] File generator failed: {exc}"
            logger.error(msg, exc_info=True)
            summary['errors'].append(msg)

    if summary['quarters']:
        summary['success'] = True
        summary['quarter'] = summary['quarters'][-1]
        if last_gen:
            summary['data_xlsx'] = last_gen.get('data_xlsx')
            summary['meta_xlsx'] = last_gen.get('meta_xlsx')
            summary['zip']       = last_gen.get('zip')

    return summary
