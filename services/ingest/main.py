import os, logging, time, signal, sys, json, uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests, boto3
from tqdm import tqdm
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuration
BUCKET = os.getenv("S3_BUCKET", "scotustician")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 8))
START_TERM = int(os.getenv("START_TERM", 1980))
END_TERM = int(os.getenv("END_TERM", 2025))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

OYEZ_CASES_TERM_PREFIX = 'https://api.oyez.org/cases?per_page=0&filter=term:'
OYEZ_API_BASE = 'https://api.oyez.org'

# Global state for shutdown handling
shutdown_requested = False
active_futures = []
executor_lock = None
s3 = boto3.client('s3')

def signal_handler(signum, _):
    """Handle shutdown signals gracefully"""
    global shutdown_requested
    shutdown_requested = True
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Shutting down gracefully...")
    
    if executor_lock:
        with executor_lock:
            logger.info(f"Cancelling {len(active_futures)} active tasks...")
            for future in active_futures:
                future.cancel()
    
    sys.exit(0)

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal handlers configured for graceful shutdown")

@sleep_and_retry
@limits(calls=1, period=1)  # 1 call per second rate limiting
@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError))
)
def _limited_request(url: str) -> requests.Response:
    """Rate-limited HTTP request with retries"""
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': 'scotustician/1.0'})
    response.raise_for_status()
    return response

def request(url: str) -> Optional[Dict]:
    """Make API request and return JSON response"""
    try:
        response = _limited_request(url)
        return response.json()
    except Exception as e:
        logger.error(f"Request failed for {url}: {e}")
        return None

def get_existing_oa_ids() -> set:
    """Get existing oral argument IDs from S3 to avoid duplicates"""
    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix='raw/oral_arguments/')
        existing_ids = set()
        
        for obj in response.get('Contents', []):
            try:
                # Extract OA ID from S3 key if possible
                key = obj['Key']
                if 'oa_' in key:
                    oa_id = key.split('oa_')[1].split('_')[0]
                    existing_ids.add(int(oa_id))
            except (ValueError, IndexError):
                continue
        
        logger.info(f"Found {len(existing_ids)} existing OA records in S3")
        return existing_ids
    except Exception as e:
        logger.warning(f"Could not get existing OA IDs: {e}")
        return set()

def log_junk_to_s3(term: int, item: Any, context: str):
    """Log problematic data to S3 for analysis"""
    try:
        junk_id = uuid.uuid4().hex
        junk_record = {
            "junk_id": junk_id,
            "term": term,
            "context": context,
            "item": str(item)[:10000],  # Truncate very large items
            "logged_at": datetime.now().isoformat()
        }
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        key = f"raw/junk_data/term_{term}/junk_{junk_id}_{timestamp}.json"
        
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(junk_record, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Logged junk data: {context} for term {term}")
    except Exception as e:
        logger.error(f"Failed to log junk data: {e}")

def get_cases_by_term(term: int) -> List[Dict]:
    """Get all cases for a given Supreme Court term"""
    cases_url = f"{OYEZ_CASES_TERM_PREFIX}{term}"
    cases = request(cases_url)
    
    if not isinstance(cases, list):
        logger.warning(f"Unexpected response format for term {term}: {type(cases)}")
        return []
    
    logger.info(f"Found {len(cases)} cases for term {term}")
    return cases

def get_case_full(term: int, docket_number: str) -> Optional[Dict]:
    """Get full case details including oral arguments"""
    case_url = f"{OYEZ_API_BASE}/cases/{term}/{docket_number}"
    return request(case_url)

def process_oa(oa_href: str, oa_id: int, term: int, docket_number: str, session: int, case_id: Optional[str] = None) -> Optional[Dict]:
    """Process a single oral argument"""
    if shutdown_requested:
        return None
    
    try:
        oa_data = request(oa_href)
        if not oa_data:
            return None
        
        # Add metadata for tracking
        oa_data.update({
            "id": oa_id,
            "term": term,
            "case_id": case_id,
            "docket_number": docket_number,
            "session": session,
            "extracted_at": datetime.now().isoformat(),
            "extraction_id": f"{term}_{docket_number}_{oa_id}"
        })
        
        return oa_data
    except Exception as e:
        logger.error(f"Failed to process OA {oa_id}: {e}")
        return None

def process_case(term: int, case: Dict, existing_oa_ids: set) -> List[Dict]:
    """Process a single case and return its oral arguments"""
    if shutdown_requested:
        return []
    
    if not isinstance(case, dict):
        log_junk_to_s3(term, case, "non_dict_case")
        return []
    
    docket_number = case.get("docket_number")
    if not docket_number:
        log_junk_to_s3(term, case, "missing_docket_number")
        return []
    
    # Get full case details
    case_full = get_case_full(term, docket_number)
    if not case_full:
        return []
    
    # Check for oral arguments
    oral_argument_audio = case_full.get('oral_argument_audio', [])
    if not oral_argument_audio:
        return []
    
    logger.info(f"Found {len(oral_argument_audio)} oral argument(s) for case {docket_number}")
    
    oral_arguments = []
    for idx, oa in enumerate(oral_argument_audio):
        oa_href = oa.get('href')
        oa_id = oa.get('id')
        
        if not oa_href or not oa_id:
            continue
        
        # Skip if we already have this OA
        if oa_id in existing_oa_ids:
            logger.info(f"Skipping existing OA {oa_id}")
            continue
        
        oa_data = process_oa(oa_href, oa_id, term, docket_number, idx, case.get('ID'))
        if oa_data:
            oral_arguments.append(oa_data)
    
    return oral_arguments

def write_summary_to_s3(summary: Dict):
    """Write ingestion summary to S3"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        key = f"raw/ingestion_summary/summary_{timestamp}.json"
        
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(summary, indent=2, default=str),
            ContentType='application/json'
        )
        logger.info(f"Uploaded summary to s3://{BUCKET}/{key}")
    except Exception as e:
        logger.error(f"Failed to upload summary: {e}")

def print_sample_data_validation(oral_arguments: List[Dict]):
    """Print sample data for validation"""
    if oral_arguments:
        sample = oral_arguments[0]
        logger.info(f"Sample OA keys: {list(sample.keys())}")
        logger.info(f"Sample ID: {sample.get('id')}")
        logger.info(f"Sample term: {sample.get('term')}")

def main():
    """Main ingestion process"""
    global executor_lock
    
    setup_signal_handlers()
    
    logger.info(f"Starting Oyez ingestion | Workers={MAX_WORKERS}")
    logger.info(f"Processing terms {START_TERM} to {END_TERM-1}")
    
    start_time = time.time()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Get existing OA IDs to avoid duplicates
    existing_oa_ids = get_existing_oa_ids()
    
    all_oral_arguments = []
    total_cases = 0
    processed_terms = 0
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor_lock = executor._threads_queues[1]  # Access to internal lock
            
            for term in range(START_TERM, END_TERM):
                if shutdown_requested:
                    break
                
                logger.info(f"Processing term {term}")
                
                # Get cases for this term
                cases = get_cases_by_term(term)
                if not cases:
                    continue
                
                total_cases += len(cases)
                
                # Process cases in parallel
                with tqdm(total=len(cases), desc=f"Term {term}") as pbar:
                    future_to_case = {
                        executor.submit(process_case, term, case, existing_oa_ids): case 
                        for case in cases
                    }
                    active_futures.extend(future_to_case.keys())
                    
                    for future in as_completed(future_to_case):
                        if shutdown_requested:
                            break
                        
                        try:
                            oral_arguments = future.result()
                            all_oral_arguments.extend(oral_arguments)
                            pbar.update(1)
                        except Exception as e:
                            case = future_to_case[future]
                            logger.error(f"Case processing failed: {e}")
                        finally:
                            active_futures.remove(future)
                
                processed_terms += 1
                logger.info(f"Term {term} completed: {len([oa for oa in all_oral_arguments if oa.get('term') == term])} OA records")
        
        if not shutdown_requested:
            # Upload results to S3
            if all_oral_arguments:
                print_sample_data_validation(all_oral_arguments)
                
                # Split data by term for better organization
                for term in range(START_TERM, END_TERM):
                    term_oas = [oa for oa in all_oral_arguments if oa.get('term') == term]
                    if term_oas:
                        key = f"raw/oral_arguments/term_{term}/oral_arguments_{term}_{timestamp}.json"
                        s3.put_object(
                            Bucket=BUCKET,
                            Key=key,
                            Body=json.dumps(term_oas, indent=2, default=str),
                            ContentType='application/json'
                        )
                        logger.info(f"Uploaded {len(term_oas)} OA records for term {term}")
            
            # Create and upload summary
            total_duration = time.time() - start_time
            summary = {
                "ingestion_completed_at": datetime.now().isoformat(),
                "start_term": START_TERM,
                "end_term": END_TERM - 1,
                "processed_terms": processed_terms,
                "total_cases": total_cases,
                "total_oral_arguments": len(all_oral_arguments),
                "total_duration_seconds": total_duration,
                "average_duration_per_term": total_duration / max(processed_terms, 1)
            }
            
            write_summary_to_s3(summary)
            
            logger.info("Ingestion completed successfully!")
            logger.info(f"Total: {len(all_oral_arguments)} oral arguments from {total_cases} cases across {processed_terms} terms")
            logger.info(f"Duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()