import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

from helpers import (
    get_existing_oa_ids,
    get_cases_by_term,
    process_case,
    process_oa,
    write_summary_to_s3,
    log_junk_to_s3,
    print_sample_data_validation,
    BUCKET
)

from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))
START_TERM = int(os.getenv("START_TERM", 1980))
END_TERM = int(os.getenv("END_TERM", 2025))

def main() -> None:
    logger.info(f"Starting Oyez ingestion | Workers={MAX_WORKERS}")
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    logger.info("Scanning S3 bucket for existing oral arguments...")
    existing_oa_ids = get_existing_oa_ids()
    
    tasks = []
    diff_stats = {
        "total_oas_checked": 0,
        "existing_oas_skipped": 0,
        "new_oas_to_download": 0
    }

    cases_total = 0
    cases_with_docket = 0
    cases_with_oa = 0
    cases_skipped = 0
    total_uploaded = 0
    total_bytes = 0

    for term in tqdm(range(START_TERM, END_TERM), desc="Gathering tasks by term"):
        try:
            cases = get_cases_by_term(term)
            if not cases:
                logger.warning(f"No cases returned for term {term}")
                continue
            for case in cases:
                cases_total += 1

                if not isinstance(case, dict):
                    logger.error(f"Skipping malformed case (term {term}): expected dict but got {type(case)} - {case}")
                    log_junk_to_s3(term, case, context="non_dict_case")
                    cases_skipped += 1
                    continue

                docket_number = case.get("docket_number")
                if not docket_number:
                    logger.warning(f"Skipping case without docket number: {case}")
                    log_junk_to_s3(term, case, context="missing_docket_number")
                    cases_skipped += 1
                    continue

                logger.info(f"Found case with docket number: {docket_number} (term {term})")
                cases_with_docket += 1

                try:
                    subtasks, case_stats = process_case(term, case, timestamp, existing_oa_ids)
                    diff_stats["total_oas_checked"] += case_stats["checked"]
                    diff_stats["existing_oas_skipped"] += case_stats["existing"]
                    diff_stats["new_oas_to_download"] += case_stats["new"]
                    
                    if subtasks:
                        cases_with_oa += 1
                    else:
                        cases_skipped += 1
                    tasks.extend(subtasks)
                except Exception as e:
                    logger.error(f"Failed to process case in term {term}: {e}")
                    log_junk_to_s3(term, case, context="process_case_exception")
                    cases_skipped += 1
        except Exception as e:
            logger.error(f"Failed to process term {term}: {e}", exc_info=True)

    logger.info("\nIncremental Load Diff Summary:")
    logger.info(f"  - Total OAs in API: {diff_stats['total_oas_checked']}")
    logger.info(f"  - Existing OAs (skipped): {diff_stats['existing_oas_skipped']}")
    logger.info(f"  - New OAs to download: {diff_stats['new_oas_to_download']}")
    logger.info(f"  - Percentage new: {(diff_stats['new_oas_to_download'] / max(diff_stats['total_oas_checked'], 1) * 100):.1f}%")
    
    if len(tasks) == 0:
        logger.info("\nNo new oral arguments to download. S3 bucket is up to date!")
    else:
        logger.info(f"\nDispatching {len(tasks)} new oral argument tasks to thread pool...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_oa, *args) for args in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing OAs"):
            try:
                size_mb = future.result()
                if size_mb is not None:
                    total_uploaded += 1
                    total_bytes += size_mb
            except Exception as e:
                logger.error(f"Exception during task: {e}", exc_info=True)

    duration = time.time() - start_time

    summary = {
        "timestamp": timestamp,
        "cases_total": cases_total,
        "cases_with_docket": cases_with_docket,
        "cases_with_oa": cases_with_oa,
        "cases_skipped": cases_skipped,
        "oral_arguments_attempted": len(tasks),
        "oral_arguments_uploaded": total_uploaded,
        "total_data_uploaded_mb": round(total_bytes, 2),
        "total_time_seconds": round(duration, 2),
        "incremental_load": True,
        "existing_oas_in_s3": len(existing_oa_ids),
        "total_oas_checked": diff_stats["total_oas_checked"],
        "existing_oas_skipped": diff_stats["existing_oas_skipped"],
        "new_oas_downloaded": diff_stats["new_oas_to_download"],
    }

    logger.info("Ingestion Summary:")
    for k, v in summary.items():
        logger.info(f"• {k.replace('_', ' ').capitalize()}: {v}")

    write_summary_to_s3(summary, timestamp)
    
    print_sample_data_validation(total_uploaded)

if __name__ == "__main__":
    main()