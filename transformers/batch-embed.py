import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from helpers import (
    get_transcript_s3,
    generate_case_embedding,
    extract_metadata_from_key,
    ensure_index_exists,
    index_case_embedding_to_opensearch
)

import boto3
from opensearchpy import OpenSearch

BUCKET = os.getenv("S3_BUCKET", "scotustician")
PREFIX = os.getenv("RAW_PREFIX", "raw/oa")
INDEX_NAME = os.getenv("INDEX_NAME", "scotus-oa-embeddings")
MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 16))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 2))

s3 = boto3.client("s3")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

os_client = OpenSearch(
    hosts=[{'host': os.getenv("OPENSEARCH_HOST", "localhost"), 'port': 443}],
    http_auth=('admin', os.getenv("OPENSEARCH_PASS", "")),
    use_ssl=True,
    verify_certs=True
)

def list_s3_keys(bucket: str, prefix: str):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]

def process_key(key: str):
    try:
        chunks = get_transcript_s3(BUCKET, key)
        embedding, text = generate_case_embedding(chunks, MODEL_NAME, BATCH_SIZE)
        meta = extract_metadata_from_key(key)
        index_case_embedding_to_opensearch(embedding, text, meta, key, INDEX_NAME, os_client)
        return f"✅ Processed: {key}"
    except Exception as e:
        return f"❌ Failed: {key} | {e}"

def main():
    logger.info(f"🔍 Scanning s3://{BUCKET}/{PREFIX}")
    keys = list(list_s3_keys(BUCKET, PREFIX))
    ensure_index_exists(os_client, INDEX_NAME)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_key, key) for key in keys]
        for future in as_completed(futures):
            logger.info(future.result())

    logger.info("🎉 Batch embedding complete.")

if __name__ == "__main__":
    main()
