"""
Pipeline orchestrator for LICIPD data extraction.

Coordinates the three pipeline stages:
  1. scraper.download()       -> pdf_paths dict
  2. extractor.extract()      -> (quarter, data dict)
  3. file_generator.generate() -> output files

Returns a summary dict describing what was done.
"""

import json
import os
import logging
from datetime import datetime

import scraper
import extractor
import file_generator
import config

logger = logging.getLogger(__name__)


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


def main():
    """
    Run the full LICIPD pipeline.

    Returns dict:
        {
            'success'    : bool,
            'quarter'    : 'YYYY-QN' or None,
            'appended'   : bool,
            'data_xlsx'  : path or None,
            'meta_xlsx'  : path or None,
            'zip'        : path or None,
            'run_dir'    : path,
            'errors'     : [str, ...],
        }
    """
    summary = {
        'success':   False,
        'skipped':   False,
        'quarter':   None,
        'appended':  False,
        'data_xlsx': None,
        'meta_xlsx': None,
        'zip':       None,
        'run_dir':   None,
        'errors':    [],
    }

    # ── Stage 1: Download PDFs ───────────────────────────────────────────────
    logger.info("=== Stage 1: Scraper ===")
    try:
        pdf_paths = scraper.download()
        summary['run_dir']  = pdf_paths.get('run_dir')
        summary['quarter']  = pdf_paths.get('quarter')

        # ── Already-processed early exit ─────────────────────────────────
        if pdf_paths.get('skipped'):
            summary['skipped'] = True
            summary['success'] = True
            logger.info("Pipeline halted: NO NEW DATA")
            return summary

        missing_cats = [
            cat for cat in ('balance_sheet', 'investments_policyholders',
                            'investments_linked', 'revenue_account')
            if not pdf_paths.get(cat)
        ]
        if missing_cats:
            msg = f"Missing PDFs for categories: {missing_cats}"
            logger.warning(msg)
            summary['errors'].append(msg)

        if not any(pdf_paths.get(cat) for cat in
                   ('balance_sheet', 'investments_policyholders',
                    'investments_linked', 'revenue_account')):
            raise RuntimeError("Scraper returned no PDFs at all")

        logger.info(
            f"Scraper complete: BS={len(pdf_paths.get('balance_sheet', []))} "
            f"PH={len(pdf_paths.get('investments_policyholders', []))} "
            f"LNK={len(pdf_paths.get('investments_linked', []))} "
            f"REV={len(pdf_paths.get('revenue_account', []))}"
        )

    except Exception as exc:
        msg = f"Scraper failed: {exc}"
        logger.error(msg, exc_info=True)
        summary['errors'].append(msg)
        return summary

    # ── Stage 2: Extract data from PDFs ─────────────────────────────────────
    logger.info("=== Stage 2: Extractor ===")
    try:
        quarter, data = extractor.extract(pdf_paths)
        summary['quarter'] = quarter

        if not quarter:
            msg = "Quarter could not be determined from PDFs"
            logger.warning(msg)
            summary['errors'].append(msg)

        # Scraper may also have detected the quarter — use as fallback
        if not quarter and pdf_paths.get('quarter'):
            quarter = pdf_paths['quarter']
            summary['quarter'] = quarter
            logger.info(f"Using quarter from scraper URL detection: {quarter}")

        if not quarter:
            raise RuntimeError("Quarter label could not be determined")

        na_count = sum(1 for v in data.values() if v == 'NA')
        logger.info(f"Extraction complete: quarter={quarter}  NA fields={na_count}/56")

    except Exception as exc:
        msg = f"Extractor failed: {exc}"
        logger.error(msg, exc_info=True)
        summary['errors'].append(msg)
        return summary

    # ── Stage 3: Generate output files ──────────────────────────────────────
    logger.info("=== Stage 3: File Generator ===")
    try:
        gen_result = file_generator.generate(quarter, data)
        summary['appended']  = gen_result.get('appended', False)
        summary['data_xlsx'] = gen_result.get('data_xlsx')
        summary['meta_xlsx'] = gen_result.get('meta_xlsx')
        summary['zip']       = gen_result.get('zip')
        summary['success']   = True

        logger.info(
            f"Output complete: appended={summary['appended']}  "
            f"zip={summary['zip']}"
        )

        # Save state so future runs can detect this quarter was processed
        _save_processed_state(quarter, pdf_paths.get('date_text'))

    except Exception as exc:
        msg = f"File generator failed: {exc}"
        logger.error(msg, exc_info=True)
        summary['errors'].append(msg)

    return summary
