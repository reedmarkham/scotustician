import os
import subprocess
import logging
import time
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
            yield {"Key": obj["Key"], "Size": obj["Size"]}

def output_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError:
        return False

def run_pipeline(obj: dict):
    input_key = obj["Key"]
    input_size = obj["Size"]

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

    start = time.time()
    try:
        subprocess.run(cmd, check=True)
        duration = time.time() - start
        size_mb = input_size / (1024 * 1024)
        return f"✅ Processed: {input_key} | {size_mb:.2f} MB | ⏱ {duration:.2f}s"
    except subprocess.CalledProcessError as e:
        duration = time.time() - start
        return f"❌ Failed: {input_key} | ⏱ {duration:.2f}s | Error: {e}"

def main():
    logger.info(f"📦 Scanning S3 for keys under s3://{INPUT_BUCKET}/{RAW_PREFIX}")
    objects = list(list_s3_keys(INPUT_BUCKET, RAW_PREFIX))
    logger.info(f"🧮 Found {len(objects)} keys")

    start_time = time.time()
    processed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(run_pipeline, obj): obj for obj in objects}
        for future in as_completed(futures):
            result = future.result()
            logger.info(result)
            if result.startswith("✅ Processed"):
                processed += 1

    total_duration = time.time() - start_time
    logger.info(f"🎉 Completed {processed} file(s) in {total_duration:.2f} seconds.")

if __name__ == "__main__":
    main()
