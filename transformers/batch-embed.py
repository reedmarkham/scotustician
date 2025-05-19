import os
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

# --- Config ---
INPUT_BUCKET = os.environ.get("S3_BUCKET", "scotustician")
RAW_PREFIX = "raw/"
OUTPUT_PREFIX = "oa-embeddings/"
INDEX_NAME = "scotus-oa-embeddings"
MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = "16"
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))

# --- Setup ---
s3 = boto3.client("s3")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def list_s3_keys(bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]

def output_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError:
        return False

def run_pipeline(input_key: str):
    if not input_key.endswith(".json"):
        return f"⏩ Skipped (not JSON): {input_key}"

    output_key = input_key.replace(RAW_PREFIX, OUTPUT_PREFIX)
    if output_exists(INPUT_BUCKET, output_key):
        return f"✅ Skipped (already processed): {input_key}"

    cmd = [
        "python", "main.py",
        "--input-bucket", INPUT_BUCKET,
        "--input-key", input_key,
        "--output-key", output_key,
        "--index-name", INDEX_NAME,
        "--model", MODEL,
        "--batch-size", BATCH_SIZE
    ]

    try:
        subprocess.run(cmd, check=True)
        return f"✅ Processed: {input_key}"
    except subprocess.CalledProcessError as e:
        return f"❌ Failed: {input_key} | Error: {e}"

def main():
    logger.info(f"📦 Scanning S3 for keys under s3://{INPUT_BUCKET}/{RAW_PREFIX}")
    keys = list(list_s3_keys(INPUT_BUCKET, RAW_PREFIX))
    logger.info(f"🧮 Found {len(keys)} keys")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(run_pipeline, key): key for key in keys}
        for future in as_completed(futures):
            result = future.result()
            logger.info(result)

    logger.info("🎉 Parallel batch job complete.")

if __name__ == "__main__":
    main()
