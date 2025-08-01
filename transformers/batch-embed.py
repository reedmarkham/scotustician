import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from helpers import (
    extract_speaker_list,
    get_transcript_s3,
    generate_case_embedding,
    generate_utterance_embeddings,
    extract_metadata_from_key,
    ensure_tables_exist,
    insert_case_embedding_to_postgres,
    insert_utterance_embeddings_to_postgres
)

import boto3
import psycopg2

BUCKET = os.getenv("S3_BUCKET", "scotustician")
PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
INDEX_NAME = os.getenv("INDEX_NAME", "oa-embeddings")
MODEL_NAME = os.getenv("MODEL_NAME", "nvidia/NV-Embed-v2")
MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 4096))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 4))  # Reduced for large NV-Embed-v2 model
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 2))

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
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]

def process_key(key: str):
    try:
        xml_string = get_transcript_s3(BUCKET, key)
        speaker_list = extract_speaker_list(xml_string)
        meta = extract_metadata_from_key(key)
        
        # Generate both case-level and utterance-level embeddings
        embedding, text = generate_case_embedding(xml_string, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
        utterances = generate_utterance_embeddings(xml_string, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
        
        with get_db_connection() as conn:
            # Insert case-level embedding (for backward compatibility)
            insert_case_embedding_to_postgres(
                embedding, text, meta, key, conn, speaker_list
            )
            # Insert utterance-level embeddings
            insert_utterance_embeddings_to_postgres(
                utterances, meta, key, conn
            )
        
        return f"✅ Processed: {key} ({len(utterances)} utterances)"
    except Exception as e:
        return f"❌ Failed: {key} | {e}"


def main():
    logger.info(f"Scanning s3://{BUCKET}/{PREFIX}")
    keys = list(list_s3_keys(BUCKET, PREFIX))
    
    with get_db_connection() as conn:
        ensure_tables_exist(conn)

    processed_count = 0
    failed_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_key, key) for key in keys]
        for future in as_completed(futures):
            result = future.result()
            logger.info(result)
            if result.startswith("✅"):
                processed_count += 1
            else:
                failed_count += 1

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
                
                # Validate utterance embeddings
                cursor.execute("SELECT COUNT(*) FROM scotustician.utterance_embeddings")
                utterance_count = cursor.fetchone()[0]
                logger.info(f"\nTotal utterance embeddings: {utterance_count}")
                
                # Get utterance stats by case
                cursor.execute("""
                    SELECT 
                        case_id,
                        COUNT(*) as utterance_count,
                        COUNT(DISTINCT speaker_name) as speaker_count,
                        AVG(word_count) as avg_words,
                        MIN(utterance_index) as min_idx,
                        MAX(utterance_index) as max_idx
                    FROM scotustician.utterance_embeddings
                    GROUP BY case_id
                    ORDER BY case_id DESC
                    LIMIT 5
                """)
                
                logger.info("\nRecent case utterance stats:")
                for row in cursor.fetchall():
                    logger.info(f"  - Case: {row[0]}")
                    logger.info(f"    Utterances: {row[1]}")
                    logger.info(f"    Speakers: {row[2]}")
                    logger.info(f"    Avg words/utterance: {row[3]:.1f}")
                    logger.info("")
                    
    except Exception as e:
        logger.error(f"Failed to validate database: {e}")

if __name__ == "__main__":
    main()
