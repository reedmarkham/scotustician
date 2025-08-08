import os, logging
from typing import Dict, Any

from helpers import (
    extract_metadata_from_key,
    get_db_connection,
    verify_tables_exist,
    process_transcript_with_chunking,
    insert_document_chunk_embeddings
)

import ray, ray.data, psycopg2

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
        verify_tables_exist(conn)
        
        # Use section-based chunking approach
        chunks = process_transcript_with_chunking(
            bucket, input_key, model_name, model_dimension, batch_size, conn, meta
        )
        
        insert_document_chunk_embeddings(chunks, conn)
        
        logger.info(f"Successfully processed single document: {input_key}")
    finally:
        conn.close()

def process_transcript_batch(batch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a batch of transcripts for Ray Data.
    This function will be called by Ray's map_batches.
    """

    BUCKET = os.getenv("S3_BUCKET", "scotustician")
    MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
    MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 24))
    
    results = []
    
    # Process each item in the batch
    for idx in range(len(batch['path'])):
        key = batch['path'][idx]
        
        try:
            meta = extract_metadata_from_key(key)
            
            with get_db_connection() as conn:
                chunks = process_transcript_with_chunking(
                    BUCKET, key, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, conn, meta
                )
                insert_document_chunk_embeddings(chunks, conn)
            
            results.append({
                'key': key,
                'status': 'success',
                'chunks_created': len(chunks),
                'error': None
            })
            logger.info(f"Processed: {key} ({len(chunks)} section chunks created)")
            
        except Exception as e:
            results.append({
                'key': key,
                'status': 'failed',
                'chunks_created': 0,
                'error': str(e)
            })
            logger.error(f"Failed: {key} | {e}")
    
    return {'results': results}

def get_unprocessed_keys_filter():
    """
    Get a filter function for incremental processing.
    Returns a function that filters out already processed keys.
    """
    if os.getenv("INCREMENTAL", "true").lower() != "true":
        return None
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT source_key 
                    FROM scotustician.document_chunk_embeddings 
                    WHERE source_key IS NOT NULL
                """)
                processed_keys = {row[0] for row in cursor.fetchall()}
                logger.info(f"Found {len(processed_keys)} already processed files in database")
                
        def filter_unprocessed(batch: Dict[str, Any]) -> Dict[str, Any]:
            """Filter out already processed keys from batch"""
            mask = [path not in processed_keys for path in batch['path']]
            return {
                'path': [p for p, m in zip(batch['path'], mask) if m]
            }
        
        return filter_unprocessed
        
    except Exception as e:
        logger.warning(f"Could not fetch processed keys from database: {e}")
        return None

def batch_process_files():
    """
    Main batch processing function using Ray Data.
    Simplified version that leverages Ray's built-in parallelization,
    fault tolerance, and memory management.
    """
    
    BUCKET = os.getenv("S3_BUCKET", "scotustician")
    PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", 1))
    FILES_PER_JOB = int(os.getenv("FILES_PER_JOB", "10"))
    
    # AWS Batch job parameters
    JOB_START_INDEX = int(os.getenv("AWS_BATCH_JOB_ARRAY_INDEX", "0"))
    
    job_id = os.getenv("AWS_BATCH_JOB_ID", f"local-{os.getpid()}")
    logger.info(f"Starting batch job {job_id} (array index: {JOB_START_INDEX})")
    logger.info(f"Configuration: Workers={MAX_WORKERS}, Files per batch={FILES_PER_JOB}")
    
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)
    
    with get_db_connection() as conn:
        verify_tables_exist(conn)
    
    try:
        ds = ray.data.read_json(
            f"s3://{BUCKET}/{PREFIX}",
            parallelism=MAX_WORKERS,
            meta_provider=ray.data.datasource.FastFileMetadataProvider()
        )
        
        total_files = ds.count()
        logger.info(f"Found {total_files} total files to process")
        
        # Calculate this job's file range
        start_idx = JOB_START_INDEX * FILES_PER_JOB
        end_idx = min(start_idx + FILES_PER_JOB, total_files)
        
        if start_idx >= total_files:
            logger.info(f"No files assigned to job array index {JOB_START_INDEX}")
            return
        
        # Take only this job's subset of files
        ds = ds.skip(start_idx).limit(FILES_PER_JOB)
        
        # Apply incremental filter if enabled
        filter_fn = get_unprocessed_keys_filter()
        if filter_fn:
            ds = ds.map_batches(filter_fn, batch_format="pandas")
            remaining = ds.count()
            logger.info(f"After filtering processed files: {remaining} files to process")
            
            if remaining == 0:
                logger.info("All files already processed")
                return
        
        results_ds = ds.map_batches(
            process_transcript_batch,
            batch_size=min(FILES_PER_JOB, 10),
            num_cpus=MAX_WORKERS,
            batch_format="pandas"
        )
        
        results = results_ds.take_all()
        
        all_results = []
        for batch_result in results:
            if 'results' in batch_result:
                all_results.extend(batch_result['results'])
        
        total_processed = sum(1 for r in all_results if r['status'] == 'success')
        total_failed = sum(1 for r in all_results if r['status'] == 'failed')
        
        logger.info("Batch job complete.")
        logger.info(f"Summary for job {job_id} (index {JOB_START_INDEX}):")
        logger.info(f"  - Files assigned: {end_idx - start_idx}")
        logger.info(f"  - Successfully processed: {total_processed}")
        logger.info(f"  - Failed: {total_failed}")

        for result in all_results:
            if result['status'] == 'failed':
                logger.error(f"Failed file: {result['key']} - {result['error']}")
        
        if total_failed > 0:
            logger.warning(f"Job completed with {total_failed} failures")
            exit(1)
        else:
            logger.info("All assigned files processed successfully")
            exit(0)
            
    except Exception as e:
        logger.error(f"Fatal error in batch processing: {e}")
        exit(1)
    finally:
        if ray.is_initialized():
            ray.shutdown()