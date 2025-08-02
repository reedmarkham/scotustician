import os
import json
import logging
from typing import Any, Optional
import time
import uuid

from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests
import boto3

logger = logging.getLogger(__name__)

BUCKET = os.getenv("S3_BUCKET", "scotustician")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

OYEZ_CASE_SUMMARY = 'https://api.oyez.org/cases?per_page=0'
OYEZ_CASES_TERM_PREFIX = 'https://api.oyez.org/cases?per_page=0&filter=term:'
s3 = boto3.client('s3')

def oyez_api_case(term: int, docket_number: str) -> str:
    return f'https://api.oyez.org/cases/{term}/{docket_number}'

def get_existing_oa_ids() -> set:
    """Retrieve all existing oral argument IDs from S3."""
    existing_ids = set()
    paginator = s3.get_paginator('list_objects_v2')
    
    try:
        for page in paginator.paginate(Bucket=BUCKET, Prefix='raw/oa/'):
            if 'Contents' in page:
                for obj in page['Contents']:
                    # Extract OA ID from key format: raw/oa/{oa_id}_{timestamp}.json
                    key = obj['Key']
                    if key.startswith('raw/oa/') and '_' in key:
                        oa_id = key.split('/')[-1].split('_')[0]
                        existing_ids.add(oa_id)
    except Exception as e:
        logger.error(f"Failed to list existing OAs from S3: {e}")
    
    logger.info(f"Found {len(existing_ids)} existing oral arguments in S3")
    return existing_ids

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
        logger.info(f"Logged junk case to s3://{BUCKET}/{key}")
    except Exception as e:
        logger.error(f"Failed to log junk to S3: {e}")

def write_summary_to_s3(summary: dict, timestamp: str):
    date_prefix = timestamp.split('_')[0]
    key = f'logs/daily/{date_prefix}/summary_{timestamp}.json'
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(summary, indent=2).encode("utf-8")
        )
        logger.info(f"Uploaded summary to s3://{BUCKET}/{key}")
    except Exception as e:
        logger.error(f"Failed to upload summary to S3: {e}")

# Make sure this is the rate limit for the Oyez API
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
        logger.info(f"Uploaded: s3://{BUCKET}/{key} | {size_mb:.2f} MB | ⏱ {duration:.2f}s")

    return size_mb

def process_case(term: int, case: dict, timestamp: str, existing_oa_ids: set) -> tuple[list, dict]:
    """Process a case and return tasks for new OAs and diff stats."""
    docket_number = case.get('docket_number')
    stats = {"checked": 0, "existing": 0, "new": 0}
    
    if not docket_number:
        logger.warning(f"Skipping case without docket number: {case}")
        log_junk_to_s3(term, case, context="missing_docket_number")
        return [], stats

    case_full = get_case_full(term, docket_number)
    if not case_full:
        logger.warning(f"No full case data for {docket_number} (term {term})")
        return [], stats
    if 'oral_argument_audio' not in case_full or not case_full['oral_argument_audio']:
        logger.info(f"No oral arguments for {docket_number} (term {term})")
        return [], stats

    oas = case_full['oral_argument_audio']
    logger.info(f"Case {docket_number} (term {term}) has {len(oas)} oral argument(s)")
    
    tasks = []
    for idx, oa in enumerate(oas):
        stats["checked"] += 1
        oa_id = oa.get('id')
        
        if oa_id and oa_id in existing_oa_ids:
            logger.debug(f"Skipping existing OA: {oa_id} for case {docket_number}")
            stats["existing"] += 1
        else:
            tasks.append((term, case, idx, oa, timestamp))
            stats["new"] += 1
            if oa_id:
                logger.info(f"New OA to download: {oa_id} for case {docket_number}")

    return tasks, stats

def print_sample_data_validation(total_uploaded: int):
    logger.info("\nSample Data Validation:")
    if total_uploaded > 0:
        try:
            # List recent uploads
            response = s3.list_objects_v2(
                Bucket=BUCKET,
                Prefix=f'raw/oa/',
                MaxKeys=5
            )
            
            if 'Contents' in response:
                logger.info("Recent S3 uploads:")
                for obj in response['Contents'][:5]:
                    logger.info(f"  - {obj['Key']} | Size: {obj['Size']/1024:.2f} KB | Modified: {obj['LastModified']}")
                
                # Download and show sample content
                sample_key = response['Contents'][0]['Key']
                sample_obj = s3.get_object(Bucket=BUCKET, Key=sample_key)
                sample_data = json.loads(sample_obj['Body'].read())
                
                logger.info(f"\nSample data from {sample_key}:")
                logger.info(f"  - Case ID: {sample_data.get('case_id', 'N/A')}")
                logger.info(f"  - Docket: {sample_data.get('docket_number', 'N/A')}")
                logger.info(f"  - Term: {sample_data.get('term', 'N/A')}")
                logger.info(f"  - Title: {sample_data.get('title', 'N/A')}")
                if 'transcript' in sample_data and 'sections' in sample_data['transcript']:
                    logger.info(f"  - Transcript sections: {len(sample_data['transcript']['sections'])}")
                    
        except Exception as e:
            logger.error(f"Failed to print sample data: {e}")