import argparse
import logging
import time
import os

from helpers import (
    get_transcript_s3,
    generate_embeddings,
    save_embeddings,
    index_to_opensearch,
    extract_metadata_from_key
)
from opensearchpy import OpenSearch, RequestsHttpConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Generate embeddings and save to S3 + OpenSearch.")
    parser.add_argument("--input-bucket", required=True)
    parser.add_argument("--input-key", required=True)
    parser.add_argument("--output-key", required=True, help="S3 key for embeddings")
    parser.add_argument("--index-name", required=True)
    parser.add_argument("--model", default="all-MiniLM-L6-v2")
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    try:
        start = time.time()

        logger.info("🚀 Starting embedding + indexing pipeline")
        chunks = get_transcript_s3(args.input_bucket, args.input_key)

        if not chunks:
            raise ValueError("Transcript is empty or missing.")

        embeddings = generate_embeddings(chunks, model_name=args.model, batch_size=args.batch_size)

        metadata = extract_metadata_from_key(args.input_key)

        # Output to S3
        save_embeddings(
            embeddings=embeddings,
            chunks=chunks,
            bucket=args.input_bucket,
            key=args.output_key,
            metadata=metadata
        )

        # Output to OpenSearch
        os_host = os.environ.get("OPENSEARCH_HOST")
        if not os_host:
            raise ValueError("❌ OPENSEARCH_HOST environment variable is not set")

        os_client = OpenSearch(
            hosts=[os_host],
            http_compress=True,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
        )

        index_to_opensearch(
            embeddings=embeddings,
            chunks=chunks,
            index_name=args.index_name,
            os_client=os_client,
            source_key=args.input_key
        )

        logger.info(f"✅ Finished pipeline. Elapsed: {time.time() - start:.2f}s")

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
