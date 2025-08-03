import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

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

# Validate Postgres env vars
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASS = os.getenv("POSTGRES_PASS")
POSTGRES_DB = os.getenv("POSTGRES_DB")

if not all([POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASS, POSTGRES_DB]):
    raise EnvironmentError("Missing required Postgres environment variables")

logger.info(f"Connecting to Postgres at {POSTGRES_HOST}")

def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
        database=POSTGRES_DB
    )

def list_s3_keys(bucket: str, prefix: str):
    paginator = s3.get_paginator("list_objects_v2")
    logger.info(f"Listing objects in s3://{bucket}/{prefix}...")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    logger.info(f"Found {len(keys)} objects to process")
    return keys

def process_key(key: str):
    try:
        meta = extract_metadata_from_key(key)
        
        with get_db_connection() as conn:
            # Use new chunking approach
            chunks = process_transcript_with_chunking(
                BUCKET, key, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, conn, meta
            )
            
            # Insert document chunk embeddings
            insert_document_chunk_embeddings(chunks, conn)
            
            # Generate case-level embedding (for backward compatibility if needed)
            # Note: This now uses the first chunk's XML for the case embedding
            if chunks:
                chunk_xml = chunks[0].get('chunk_xml', '')
                if chunk_xml:
                    speaker_list = extract_speaker_list(chunk_xml)
                    embedding, text = generate_case_embedding(chunk_xml, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
                    insert_case_embedding_to_postgres(
                        embedding, text, meta, key, conn, speaker_list
                    )
        
        return f"✅ Processed: {key} ({len(chunks)} section chunks created)"
    except Exception as e:
        return f"❌ Failed: {key} | {e}"


def main():
    logger.info(f"Scanning s3://{BUCKET}/{PREFIX}")
    logger.info("Using section-based chunking approach")
    logger.info(f"Model: {MODEL_NAME} (dimension: {MODEL_DIMENSION})")
    logger.info(f"Batch size: {BATCH_SIZE}, Max workers: {MAX_WORKERS}")
    
    keys = list_s3_keys(BUCKET, PREFIX)
    
    with get_db_connection() as conn:
        ensure_tables_exist(conn)

    processed_count = 0
    failed_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_key, key): key for key in keys}
        
        with tqdm(total=len(keys), desc="Processing transcripts", unit="files") as pbar:
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    logger.info(result)
                    if result.startswith("✅"):
                        processed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"❌ Exception processing {key}: {e}")
                    failed_count += 1
                pbar.update(1)

    logger.info("Batch embedding complete.")
    logger.info(f"Summary: Processed {processed_count}, Failed {failed_count}")
    
    # Print sample data for validation
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
