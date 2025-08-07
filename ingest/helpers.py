import os, json, logging, time, uuid
from typing import Any, Optional, Dict, Iterator
from datetime import datetime

import requests, boto3
import dlt
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

BUCKET = os.getenv("S3_BUCKET", "scotustician")

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



# DLT-compatible junk data handling functions
def log_junk_data_to_dlt(pipeline, term: int, item: Any, context: str):
    """Log junk data using dlt pipeline - integrated junk_handler functionality"""
    junk_id = uuid.uuid4().hex
    junk_record = {
        "junk_id": junk_id,
        "term": term,
        "context": context,
        "item": str(item)[:10000],  # Truncate very large items
        "timestamp": datetime.now().isoformat(),
        "_dlt_extracted_at": datetime.now()
    }
    
    # Create a simple source for this single record
    @dlt.source
    def single_junk_record():
        @dlt.resource(write_disposition="append", table_name="junk_data")
        def junk_item():
            yield junk_record
        return junk_item
    
    # Run the junk data pipeline
    try:
        load_info = pipeline.run(single_junk_record())
        logger.info(f"Logged junk data: {context} for term {term}")
    except Exception as e:
        logger.error(f"Failed to log junk data: {e}")

def print_sample_data_validation(total_uploaded: int):
    """Sample data validation for uploaded records"""
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

# Legacy function for backward compatibility - use DLT pipeline instead
def legacy_log_junk_to_s3(term: int, item: Any, context: str):
    """Legacy function - use DLT pipeline junk handling instead"""
    logger.warning("legacy_log_junk_to_s3 is deprecated, use DLT pipeline junk handling")
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