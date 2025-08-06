import os
import signal
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import threading
import time

# Disable tokenizers parallelism to avoid warnings in multi-threaded environment
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from helpers import (
    extract_speaker_list,
    generate_case_embedding,
    process_transcript_with_chunking,
    extract_metadata_from_key,
    ensure_tables_exist,
    insert_case_embedding_to_postgres,
    insert_document_chunk_embeddings,
    process_single_document
)

import boto3
import psycopg2

BUCKET = os.getenv("S3_BUCKET", "scotustician")
PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 24))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 1))
INCREMENTAL = os.getenv("INCREMENTAL", "true").lower() == "true"

s3 = boto3.client("s3")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Global shutdown flag
shutdown_requested = threading.Event()
active_futures = set()
executor_lock = threading.Lock()

# Validate Postgres env vars
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")
POSTGRES_DB = os.getenv("POSTGRES_DB")

if not all([POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASS, POSTGRES_DB]):
    raise EnvironmentError("Missing required Postgres environment variables")

logger.info(f"Connecting to Postgres at {POSTGRES_HOST}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested.set()

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal handlers configured for graceful shutdown")

def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
        database=POSTGRES_DB
    )

def get_processed_keys():
    """Get list of keys that have already been processed"""
    processed_keys = set()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT s3_key 
                    FROM scotustician.transcript_embeddings 
                    WHERE s3_key IS NOT NULL
                """)
                processed_keys = {row[0] for row in cursor.fetchall()}
                logger.info(f"Found {len(processed_keys)} already processed files in database")
    except Exception as e:
        logger.warning(f"Could not fetch processed keys from database: {e}")
    return processed_keys

def list_s3_keys(bucket: str, prefix: str):
    paginator = s3.get_paginator("list_objects_v2")
    logger.info(f"Listing objects in s3://{bucket}/{prefix}...")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if shutdown_requested.is_set():
            logger.info("Shutdown requested during S3 listing, stopping...")
            break
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    
    if INCREMENTAL:
        processed_keys = get_processed_keys()
        initial_count = len(keys)
        keys = [k for k in keys if k not in processed_keys]
        logger.info(f"Incremental mode: filtered {initial_count - len(keys)} already processed files")
    
    logger.info(f"Found {len(keys)} objects to process")
    return keys

def process_key(key: str):
    """Process a single key with interruption checking"""
    if shutdown_requested.is_set():
        return f"⏹️ Skipped: {key} (shutdown requested)"
    
    try:
        meta = extract_metadata_from_key(key)
        
        # Check for shutdown before heavy processing
        if shutdown_requested.is_set():
            return f"⏹️ Interrupted: {key} (shutdown during processing)"
        
        with get_db_connection() as conn:
            # Use new chunking approach
            chunks = process_transcript_with_chunking(
                BUCKET, key, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, conn, meta
            )
            
            if shutdown_requested.is_set():
                logger.warning(f"Shutdown requested during chunking for {key}")
                return f"⏹️ Interrupted: {key} (shutdown during chunking)"
            
            # Insert document chunk embeddings
            insert_document_chunk_embeddings(chunks, conn)
            
            # Generate case-level embedding (for backward compatibility if needed)
            # Note: This now uses the first chunk's XML for the case embedding
            if chunks and not shutdown_requested.is_set():
                chunk_xml = chunks[0].get('chunk_xml', '')
                if chunk_xml:
                    speaker_list = extract_speaker_list(chunk_xml)
                    embedding, text = generate_case_embedding(chunk_xml, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
                    insert_case_embedding_to_postgres(
                        embedding, text, meta, key, conn, speaker_list
                    )
        
        if shutdown_requested.is_set():
            return f"⏹️ Interrupted: {key} (shutdown after processing)"
        
        return f"✅ Processed: {key} ({len(chunks)} section chunks created)"
    except Exception as e:
        if shutdown_requested.is_set():
            return f"⏹️ Interrupted: {key} | {e}"
        return f"❌ Failed: {key} | {e}"


def graceful_shutdown_executor(executor, timeout=30):
    """Gracefully shutdown ThreadPoolExecutor with timeout"""
    logger.info(f"Initiating graceful shutdown of executor (timeout: {timeout}s)...")
    
    # Cancel pending futures
    cancelled_count = 0
    with executor_lock:
        for future in list(active_futures):
            if future.cancel():
                cancelled_count += 1
    
    logger.info(f"Cancelled {cancelled_count} pending tasks")
    
    # Shutdown executor
    executor.shutdown(wait=False)
    
    # Wait for running tasks to complete with timeout
    start_time = time.time()
    while time.time() - start_time < timeout:
        with executor_lock:
            running_futures = [f for f in active_futures if f.running()]
        if not running_futures:
            logger.info("All running tasks completed gracefully")
            return True
        time.sleep(0.5)
    
    logger.warning(f"Timeout reached, {len(running_futures)} tasks may still be running")
    return False

def main():
    # Setup signal handlers first
    setup_signal_handlers()
    
    logger.info(f"Scanning s3://{BUCKET}/{PREFIX}")
    logger.info("Using section-based chunking approach")
    logger.info(f"Model: {MODEL_NAME} (dimension: {MODEL_DIMENSION})")
    logger.info(f"Batch size: {BATCH_SIZE}, Max workers: {MAX_WORKERS}")
    logger.info(f"Incremental mode: {INCREMENTAL}")
    
    if shutdown_requested.is_set():
        logger.info("Shutdown requested before processing started")
        return
    
    keys = list_s3_keys(BUCKET, PREFIX)
    
    if shutdown_requested.is_set():
        logger.info("Shutdown requested after listing S3 keys")
        return
    
    if not keys:
        logger.info("No files to process")
        return
    
    with get_db_connection() as conn:
        ensure_tables_exist(conn)

    processed_count = 0
    failed_count = 0
    interrupted_count = 0
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all futures and track them
            futures = {}
            for key in keys:
                if shutdown_requested.is_set():
                    logger.info("Shutdown requested during task submission")
                    break
                future = executor.submit(process_key, key)
                futures[future] = key
                with executor_lock:
                    active_futures.add(future)
            
            logger.info(f"Submitted {len(futures)} tasks for processing")
            
            with tqdm(total=len(futures), desc="Processing transcripts", unit="files", 
                     disable=shutdown_requested.is_set()) as pbar:
                
                completed_futures = set()
                
                while futures and not shutdown_requested.is_set():
                    # Use a short timeout to check shutdown status regularly
                    try:
                        for future in as_completed(futures.keys(), timeout=1.0):
                            if future in completed_futures:
                                continue
                            
                            completed_futures.add(future)
                            key = futures[future]
                            
                            with executor_lock:
                                active_futures.discard(future)
                            
                            try:
                                result = future.result()
                                logger.info(result)
                                if result.startswith("✅"):
                                    processed_count += 1
                                elif result.startswith("⏹️"):
                                    interrupted_count += 1
                                else:
                                    failed_count += 1
                            except Exception as e:
                                logger.error(f"❌ Exception processing {key}: {e}")
                                failed_count += 1
                            
                            pbar.update(1)
                            
                            # Check if all futures are done
                            if len(completed_futures) == len(futures):
                                break
                    
                    except TimeoutError:
                        # Timeout is expected, just continue to check shutdown
                        continue
                
                # Handle shutdown scenario
                if shutdown_requested.is_set():
                    logger.info("Shutdown requested, initiating graceful shutdown...")
                    graceful_shutdown_executor(executor, timeout=30)
                    
                    # Count remaining unprocessed tasks
                    remaining_tasks = len(futures) - len(completed_futures)
                    if remaining_tasks > 0:
                        logger.info(f"{remaining_tasks} tasks were not completed due to shutdown")
                        interrupted_count += remaining_tasks
    
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received during processing")
        shutdown_requested.set()
    except Exception as e:
        logger.error(f"Unexpected error during processing: {e}")
        shutdown_requested.set()

    # Final summary
    total_attempted = processed_count + failed_count + interrupted_count
    logger.info("Batch embedding complete.")
    logger.info(f"Summary: Processed {processed_count}, Failed {failed_count}, Interrupted {interrupted_count}")
    logger.info(f"Total files attempted: {total_attempted}")
    
    if shutdown_requested.is_set():
        logger.info("Process was interrupted by shutdown signal")
        logger.info("Remaining files will be processed on next run (incremental mode)")
    
    # Print sample data for validation (only if not interrupted)
    if not shutdown_requested.is_set() and processed_count > 0:
        logger.info("\nDatabase Validation:")
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Count total embeddings
                    cursor.execute("SELECT COUNT(*) FROM scotustician.transcript_embeddings")
                    total_count = cursor.fetchone()[0]
                    logger.info(f"Total embeddings in database: {total_count}")
                    
                    # Get sample embeddings
                    cursor.execute("""
                        SELECT 
                            case_id,
                            case_name,
                            term,
                            speaker_list,
                            array_length(vector, 1) as embedding_dim,
                            created_at
                        FROM scotustician.transcript_embeddings
                        ORDER BY created_at DESC
                        LIMIT 5
                    """)
                    
                    logger.info("\nRecent embeddings:")
                    for row in cursor.fetchall():
                        logger.info(f"  - Case: {row[1]} (Term {row[2]})")
                        logger.info(f"    ID: {row[0]}")
                        logger.info(f"    Speakers: {', '.join(row[3][:3])}{'...' if len(row[3]) > 3 else ''}")
                        logger.info(f"    Embedding dimension: {row[4]}")
                        logger.info(f"    Created: {row[5]}")
                        logger.info("")
                    
                    # Verify embedding dimensions
                    cursor.execute("""
                        SELECT DISTINCT array_length(vector, 1) as dim, COUNT(*) as count
                        FROM scotustician.transcript_embeddings
                        GROUP BY dim
                    """)
                    logger.info("Embedding dimensions:")
                    for row in cursor.fetchall():
                        logger.info(f"  - Dimension {row[0]}: {row[1]} embeddings")
                    
                    # Validate document chunk embeddings
                    cursor.execute("SELECT COUNT(*) FROM scotustician.document_chunk_embeddings")
                    chunk_count = cursor.fetchone()[0]
                    logger.info(f"\nTotal document chunk embeddings: {chunk_count}")
                    
                    # Get chunk stats by case
                    cursor.execute("""
                        SELECT 
                            case_id,
                            COUNT(*) as chunk_count,
                            AVG(word_count) as avg_words,
                            AVG(token_count) as avg_tokens,
                            array_agg(section_id ORDER BY section_id) as section_ids
                        FROM scotustician.document_chunk_embeddings
                        GROUP BY case_id
                        ORDER BY case_id DESC
                        LIMIT 5
                    """)
                    
                    logger.info("\nRecent case chunk stats:")
                    for row in cursor.fetchall():
                        logger.info(f"  - Case: {row[0]}")
                        logger.info(f"    Sections: {row[1]} (IDs: {row[4]})")
                        logger.info(f"    Avg words/section: {row[2]:.1f}")
                        logger.info(f"    Avg tokens/section: {row[3]:.1f}")
                        logger.info("")
                    
                    # Validate oa_text table
                    cursor.execute("SELECT COUNT(*) FROM scotustician.oa_text")
                    text_count = cursor.fetchone()[0]
                    logger.info(f"\nTotal utterances in oa_text: {text_count}")
                    
                    # Get sample oa_text data
                    cursor.execute("""
                        SELECT 
                            case_id,
                            COUNT(*) as utterance_count,
                            COUNT(DISTINCT speaker_name) as speaker_count,
                            AVG(word_count) as avg_words
                        FROM scotustician.oa_text
                        GROUP BY case_id
                        ORDER BY case_id DESC
                        LIMIT 5
                    """)
                    
                    logger.info("\nRecent oa_text stats:")
                    for row in cursor.fetchall():
                        logger.info(f"  - Case: {row[0]}")
                        logger.info(f"    Utterances: {row[1]}")
                        logger.info(f"    Speakers: {row[2]}")
                        logger.info(f"    Avg words/utterance: {row[3]:.1f}")
                        logger.info("")
                        
        except Exception as e:
            logger.error(f"Failed to validate database: {e}")
    
    # Exit with appropriate code
    if shutdown_requested.is_set():
        sys.exit(130)  # 128 + SIGINT (2) - standard convention for interrupted processes
    elif failed_count > 0:
        sys.exit(1)    # Some files failed
    else:
        sys.exit(0)    # All files processed successfully

if __name__ == "__main__":
    # Check if we're processing a single document or batch
    if "INPUT_KEY" in os.environ:
        # Single document mode (legacy support)
        INPUT_KEY = os.environ["INPUT_KEY"]
        logger.info(f"Processing single document: {INPUT_KEY}")
        process_single_document(BUCKET, INPUT_KEY, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
    else:
        # Batch processing mode (default)
        main()
