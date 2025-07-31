import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from helpers import (
    extract_speaker_list,
    get_transcript_s3,
    generate_case_embedding,
    extract_metadata_from_key,
    ensure_tables_exist,
    insert_case_embedding_to_postgres
)

import boto3
import psycopg2

BUCKET = os.getenv("S3_BUCKET", "scotustician")
PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
INDEX_NAME = os.getenv("INDEX_NAME", "oa-embeddings")
MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 16))
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

logger.info(f"🔐 Connecting to Postgres at {POSTGRES_HOST}")

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
        embedding, text = generate_case_embedding(xml_string, MODEL_NAME, BATCH_SIZE)
        
        with get_db_connection() as conn:
            insert_case_embedding_to_postgres(
                embedding, text, meta, key, conn, speaker_list
            )
        
        return f"✅ Processed: {key}"
    except Exception as e:
        return f"❌ Failed: {key} | {e}"


def main():
    logger.info(f"🔍 Scanning s3://{BUCKET}/{PREFIX}")
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

    logger.info("🎉 Batch embedding complete.")
    logger.info(f"📊 Summary: Processed {processed_count}, Failed {failed_count}")
    
    # Print sample data for validation
    logger.info("\n🔍 Database Validation:")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Count total embeddings
                cursor.execute("SELECT COUNT(*) FROM scotustician.transcript_embeddings")
                total_count = cursor.fetchone()[0]
                logger.info(f"📈 Total embeddings in database: {total_count}")
                
                # Get sample embeddings
                cursor.execute("""
                    SELECT 
                        case_id,
                        docket_number,
                        term,
                        speaker_list,
                        array_length(embedding, 1) as embedding_dim,
                        created_at
                    FROM scotustician.transcript_embeddings
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                
                logger.info("\n📄 Recent embeddings:")
                for row in cursor.fetchall():
                    logger.info(f"  - Case: {row[1]} (Term {row[2]})")
                    logger.info(f"    ID: {row[0]}")
                    logger.info(f"    Speakers: {', '.join(row[3][:3])}{'...' if len(row[3]) > 3 else ''}")
                    logger.info(f"    Embedding dimension: {row[4]}")
                    logger.info(f"    Created: {row[5]}")
                    logger.info("")
                
                # Verify embedding dimensions
                cursor.execute("""
                    SELECT DISTINCT array_length(embedding, 1) as dim, COUNT(*) as count
                    FROM scotustician.transcript_embeddings
                    GROUP BY dim
                """)
                logger.info("🔢 Embedding dimensions:")
                for row in cursor.fetchall():
                    logger.info(f"  - Dimension {row[0]}: {row[1]} embeddings")
                    
    except Exception as e:
        logger.error(f"Failed to validate database: {e}")

if __name__ == "__main__":
    main()
