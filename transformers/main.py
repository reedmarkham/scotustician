import os, logging

# Disable tokenizers parallelism to avoid warnings in multi-threaded environment
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from helpers import (
    batch_process_files,
    process_single_document
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # Check if we're processing a single document or using batch mode
    if "INPUT_KEY" in os.environ:
        # Single document mode
        INPUT_KEY = os.environ["INPUT_KEY"]
        BUCKET = os.getenv("S3_BUCKET", "scotustician")
        MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
        MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
        BATCH_SIZE = int(os.getenv("BATCH_SIZE", 24))
        logger.info(f"Processing single document: {INPUT_KEY}")
        process_single_document(BUCKET, INPUT_KEY, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE)
    else:
        # AWS Batch processing mode (default)
        logger.info("Starting batch processing mode")
        batch_process_files()
