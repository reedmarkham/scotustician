import os, logging, time, sys, json
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import psycopg2

from helpers import (
    process_transcript_with_chunking,
    insert_document_chunk_embeddings,
    ensure_tables_exist,
    extract_metadata_from_key,
    get_db_connection,
    list_s3_keys,
    send_checkpoint,
    get_job_file_range,
    send_processing_message
)

logger = logging.getLogger(__name__)

def process_single_document(bucket: str, input_key: str, model_name: str, model_dimension: int, batch_size: int):
    """Process a single document for embedding generation."""
    meta = extract_metadata_from_key(input_key)
    
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS", ""),
        database=os.getenv("POSTGRES_DB", "scotustician")
    )
    
    try:
        ensure_tables_exist(conn)
        
        # Use section-based chunking approach
        chunks = process_transcript_with_chunking(
            bucket, input_key, model_name, model_dimension, batch_size, conn, meta
        )
        
        insert_document_chunk_embeddings(chunks, conn)
        
        logger.info(f"Successfully processed single document: {input_key}")
    finally:
        conn.close()

def process_key(key: str):
    """Process a single key for embedding generation"""
    BUCKET = os.getenv("S3_BUCKET", "scotustician")
    MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
    MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 24))
    
    try:
        meta = extract_metadata_from_key(key)
        
        with get_db_connection() as conn:
            chunks = process_transcript_with_chunking(
                BUCKET, key, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, conn, meta
            )
            insert_document_chunk_embeddings(chunks, conn)
        
        return f"Processed: {key} ({len(chunks)} section chunks created)"
    except Exception as e:
        return f"Failed: {key} | {e}"

def batch_process_files():
    """Main batch processing function optimized for AWS Batch with checkpointing"""
    
    # Environment configuration
    BUCKET = os.getenv("S3_BUCKET", "scotustician")
    PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
    MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
    MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 4))
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", 1))
    INCREMENTAL = os.getenv("INCREMENTAL", "true").lower() == "true"
    CHECKPOINT_FREQUENCY = int(os.getenv("CHECKPOINT_FREQUENCY", 5))
    
    # SQS Configuration
    PROCESSING_QUEUE_URL = os.getenv("PROCESSING_QUEUE_URL")
    CHECKPOINT_QUEUE_URL = os.getenv("CHECKPOINT_QUEUE_URL")
    
    # AWS Batch job parameters
    JOB_START_INDEX = int(os.getenv("AWS_BATCH_JOB_ARRAY_INDEX", "0"))
    FILES_PER_JOB = int(os.getenv("FILES_PER_JOB", "10"))
    
    job_id = os.getenv("AWS_BATCH_JOB_ID", f"local-{int(time.time())}")
    logger.info(f"Starting batch job {job_id} (array index: {JOB_START_INDEX})")
    logger.info(f"Configuration: Model={MODEL_NAME}, Batch={BATCH_SIZE}, Workers={MAX_WORKERS}")
    logger.info(f"Checkpoint frequency: every {CHECKPOINT_FREQUENCY} files")
    
    # Get all files to process
    all_keys = list_s3_keys(BUCKET, PREFIX)
    
    if not all_keys:
        logger.info("No files found to process")
        return
    
    # Get this job's subset of files
    job_keys = get_job_file_range(all_keys, JOB_START_INDEX, FILES_PER_JOB)
    
    if not job_keys:
        logger.info(f"No files assigned to job array index {JOB_START_INDEX}")
        return
    
    # Initialize database tables
    with get_db_connection() as conn:
        ensure_tables_exist(conn)
    
    processed_files = []
    failed_files = []
    checkpoint_counter = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        
        for key in job_keys:
            send_processing_message(key, 'started', PROCESSING_QUEUE_URL, JOB_START_INDEX)
            future = executor.submit(process_key, key)
            futures[future] = key
            
        logger.info(f"Submitted {len(futures)} tasks for processing")
        
        with tqdm(total=len(futures), desc=f"Job {JOB_START_INDEX}") as pbar:
            for future in as_completed(futures.keys()):
                key = futures[future]
                
                try:
                    result = future.result()
                    logger.info(result)
                    
                    if result.startswith("Processed"):
                        processed_files.append(key)
                        send_processing_message(key, 'completed', PROCESSING_QUEUE_URL, JOB_START_INDEX)
                        checkpoint_counter += 1
                        
                        # Save checkpoint every N files
                        if checkpoint_counter >= CHECKPOINT_FREQUENCY:
                            send_checkpoint(processed_files[-checkpoint_counter:], job_id, CHECKPOINT_QUEUE_URL, JOB_START_INDEX)
                            checkpoint_counter = 0
                            
                    elif result.startswith("Failed"):
                        failed_files.append(key)
                        send_processing_message(key, 'failed', PROCESSING_QUEUE_URL, JOB_START_INDEX, error=result)
                    else:
                        logger.info(f"File {key} was skipped: {result}")
                    
                except Exception as e:
                    logger.error(f"Exception processing {key}: {e}")
                    failed_files.append(key)
                    send_processing_message(key, 'failed', PROCESSING_QUEUE_URL, JOB_START_INDEX, error=str(e))
                
                pbar.update(1)
    
    # Final checkpoint with any remaining processed files
    if checkpoint_counter > 0 and processed_files:
        send_checkpoint(processed_files[-checkpoint_counter:], job_id, CHECKPOINT_QUEUE_URL, JOB_START_INDEX)
    
    # Final summary
    total_assigned = len(job_keys)
    total_processed = len(processed_files)
    total_failed = len(failed_files)
    interrupted = total_assigned - total_processed - total_failed
    
    logger.info("Batch job complete.")
    logger.info(f"Summary for job {job_id} (index {JOB_START_INDEX}):")
    logger.info(f"  - Files assigned: {total_assigned}")
    logger.info(f"  - Successfully processed: {total_processed}")
    logger.info(f"  - Failed: {total_failed}")
    logger.info(f"  - Interrupted: {interrupted}")
    
    if total_failed > 0:
        logger.warning(f"Job completed with {total_failed} failures")
        sys.exit(1)    # Some files failed
    else:
        logger.info("All assigned files processed successfully")
        sys.exit(0)    # Success