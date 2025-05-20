# Standard library imports
import os
import json
import logging
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

# Third-party libraries
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests
import boto3
from tqdm import tqdm

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# --- Environment Configuration ---
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))
START_TERM = int(os.getenv("START_TERM", 1955))
END_TERM = int(os.getenv("END_TERM", 2025))
BUCKET = os.getenv("S3_BUCKET", "scotustician")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# --- Constants ---
OYEZ_CASE_SUMMARY = 'https://api.oyez.org/cases?per_page=0'
OYEZ_CASES_TERM_PREFIX = 'https://api.oyez.org/cases?per_page=0&filter=term:'
s3 = boto3.client('s3')

# --- Helpers ---
def oyez_api_case(term: int, docket_number: str) -> str:
    return f'https://api.oyez.org/cases/{term}/{docket_number}'

@sleep_and_retry
@limits(calls=1, period=1)
def _limited_request(url: str) -> Optional[dict]:
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning(f"Rate-limited request failed: {url} | {e}")
        return None

@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True
)
def request(url: str) -> Optional[dict]:
    result = _limited_request(url)
    if result is None:
        raise Exception(f"Failed to retrieve {url}")
    return result

def get_cases_by_term(term: int) -> Optional[list]:
    return request(OYEZ_CASES_TERM_PREFIX + str(term))

def get_case_full(term: int, docket_number: str) -> Optional[dict]:
    return request(oyez_api_case(term, docket_number))

def process_oa(term: int, case: dict, session: int, oa: dict, timestamp: str) -> Optional[float]:
    case_id = case.get('ID')
    docket_number = case.get('docket_number')
    oa_id = oa.get('id')
    oa_href = oa.get('href')

    if not oa_id or not oa_href:
        logger.warning(f"Skipping malformed OA entry: {oa}")
        return None

    key = f'raw/oa/{oa_id}_{timestamp}.json'
    start_time = time.time()

    oa_json = request(oa_href)
    if oa_json is None:
        logger.warning(f"No data for OA {oa_id} (term {term}, docket {docket_number})")
        return None

    oa_json.update({
        "term": term,
        "case_id": case_id,
        "docket_number": docket_number,
        "session": session,
    })

    serialized = json.dumps(oa_json)
    size_bytes = len(serialized.encode("utf-8"))
    size_mb = size_bytes / (1024 * 1024)

    if DRY_RUN:
        logger.info(f"[DRY-RUN] Would upload: s3://{BUCKET}/{key} | Size: {size_mb:.2f} MB")
    else:
        s3.put_object(Body=serialized, Bucket=BUCKET, Key=key)
        duration = time.time() - start_time
        logger.info(f"✅ Uploaded: s3://{BUCKET}/{key} | {size_mb:.2f} MB | ⏱ {duration:.2f}s")

    return size_mb

def process_case(term: int, case: dict, timestamp: str) -> list:
    docket_number = case.get('docket_number')
    if not docket_number:
        logger.warning(f"Skipping case without docket number: {case}")
        return []

    case_full = get_case_full(term, docket_number)
    if not case_full or not case_full.get('oral_argument_audio'):
        return []

    return [
        (term, case, idx, oa, timestamp)
        for idx, oa in enumerate(case_full['oral_argument_audio'])
    ]

# --- Main driver ---
def main() -> None:
    logger.info(f"🚀 Starting Oyez ingestion | Workers={MAX_WORKERS} | Dry-run={DRY_RUN}")
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tasks = []

    for term in tqdm(range(START_TERM, END_TERM), desc="Gathering tasks by term"):
        try:
            cases = get_cases_by_term(term)
            if not cases:
                logger.warning(f"No cases returned for term {term}")
                continue
            for case in cases:
                tasks.extend(process_case(term, case, timestamp))
        except Exception as e:
            logger.error(f"Failed to process term {term}: {e}")

    logger.info(f"🧮 Dispatching {len(tasks)} oral argument tasks to thread pool...")

    total_uploaded = 0
    total_bytes = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_oa, *args) for args in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing OAs"):
            try:
                size_mb = future.result()
                if size_mb is not None:
                    total_uploaded += 1
                    total_bytes += size_mb
            except Exception as e:
                logger.error(f"Exception during task: {e}")

    duration = time.time() - start_time
    logger.info(f"🎉 Completed {total_uploaded} uploads | Total size: {total_bytes:.2f} MB | Total time: {duration:.2f}s")


if __name__ == "__main__":
    main()
