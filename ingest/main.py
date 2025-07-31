# Standard library imports
import os
import json
import logging
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import uuid

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
START_TERM = int(os.getenv("START_TERM", 2024))
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

def log_junk_to_s3(term: int, item: Any, context: str):
    junk_id = uuid.uuid4().hex
    key = f'junk/{term}_{context}_{junk_id}.json'
    body = json.dumps({
        "term": term,
        "context": context,
        "item": item
    }, indent=2)

    try:
        s3.put_object(Body=body.encode('utf-8'), Bucket=BUCKET, Key=key)
        logger.info(f"🪵 Logged junk case to s3://{BUCKET}/{key}")
    except Exception as e:
        logger.error(f"❌ Failed to log junk to S3: {e}")

def write_summary_to_s3(summary: dict, timestamp: str):
    date_prefix = timestamp.split('_')[0]
    key = f'logs/daily/{date_prefix}/summary_{timestamp}.json'
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(summary, indent=2).encode("utf-8")
        )
        logger.info(f"📤 Uploaded summary to s3://{BUCKET}/{key}")
    except Exception as e:
        logger.error(f"❌ Failed to upload summary to S3: {e}")

# --- Data functions ---
def get_cases_by_term(term: int) -> list:
    response = request(OYEZ_CASES_TERM_PREFIX + str(term))
    if not isinstance(response, list):
        raise ValueError(f"Expected list of cases, got {type(response)}")
    return response

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
        log_junk_to_s3(term, case, context="missing_docket_number")
        return []

    case_full = get_case_full(term, docket_number)
    if not case_full:
        logger.warning(f"No full case data for {docket_number} (term {term})")
        return []
    if 'oral_argument_audio' not in case_full or not case_full['oral_argument_audio']:
        logger.info(f"No oral arguments for {docket_number} (term {term})")
        return []

    logger.info(f"✅ Case {docket_number} (term {term}) has {len(case_full['oral_argument_audio'])} oral argument(s)")

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
                    logger.error(f"❌ Skipping malformed case (term {term}): expected dict but got {type(case)} - {case}")
                    log_junk_to_s3(term, case, context="non_dict_case")
                    cases_skipped += 1
                    continue

                docket_number = case.get("docket_number")
                if not docket_number:
                    logger.warning(f"Skipping case without docket number: {case}")
                    log_junk_to_s3(term, case, context="missing_docket_number")
                    cases_skipped += 1
                    continue

                logger.info(f"✅ Found case with docket number: {docket_number} (term {term})")
                cases_with_docket += 1

                try:
                    subtasks = process_case(term, case, timestamp)
                    if subtasks:
                        cases_with_oa += 1
                    else:
                        cases_skipped += 1
                    tasks.extend(subtasks)
                except Exception as e:
                    logger.error(f"❌ Failed to process case in term {term}: {e}")
                    log_junk_to_s3(term, case, context="process_case_exception")
                    cases_skipped += 1
        except Exception as e:
            logger.error(f"Failed to process term {term}: {e}", exc_info=True)

    logger.info(f"Dispatching {len(tasks)} oral argument tasks to thread pool...")

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
        "dry_run": DRY_RUN,
    }

    logger.info("📊 Ingestion Summary:")
    for k, v in summary.items():
        logger.info(f"• {k.replace('_', ' ').capitalize()}: {v}")

    write_summary_to_s3(summary, timestamp)
    
    # Print sample data for validation
    logger.info("\n🔍 Sample Data Validation:")
    if total_uploaded > 0:
        try:
            # List recent uploads
            response = s3.list_objects_v2(
                Bucket=BUCKET,
                Prefix=f'raw/oa/',
                MaxKeys=5
            )
            
            if 'Contents' in response:
                logger.info("📦 Recent S3 uploads:")
                for obj in response['Contents'][:5]:
                    logger.info(f"  - {obj['Key']} | Size: {obj['Size']/1024:.2f} KB | Modified: {obj['LastModified']}")
                
                # Download and show sample content
                sample_key = response['Contents'][0]['Key']
                sample_obj = s3.get_object(Bucket=BUCKET, Key=sample_key)
                sample_data = json.loads(sample_obj['Body'].read())
                
                logger.info(f"\n📄 Sample data from {sample_key}:")
                logger.info(f"  - Case ID: {sample_data.get('case_id', 'N/A')}")
                logger.info(f"  - Docket: {sample_data.get('docket_number', 'N/A')}")
                logger.info(f"  - Term: {sample_data.get('term', 'N/A')}")
                logger.info(f"  - Title: {sample_data.get('title', 'N/A')}")
                if 'transcript' in sample_data and 'sections' in sample_data['transcript']:
                    logger.info(f"  - Transcript sections: {len(sample_data['transcript']['sections'])}")
                    
        except Exception as e:
            logger.error(f"Failed to print sample data: {e}")


if __name__ == "__main__":
    main()
