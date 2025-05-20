import os
from opensearchpy import OpenSearch
from helpers import (
    get_transcript_s3,
    generate_case_embedding,
    extract_metadata_from_key,
    ensure_index_exists,
    index_case_embedding_to_opensearch,
)

BUCKET = os.getenv("S3_BUCKET", "scotustician")
INDEX_NAME = os.getenv("INDEX_NAME", "scotus-oa-embeddings")
MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 16))

os_client = OpenSearch(
    hosts=[{'host': os.getenv("OPENSEARCH_HOST", "localhost"), 'port': 443}],
    http_auth=('admin', os.getenv("OPENSEARCH_PASS", "")),
    use_ssl=True,
    verify_certs=True
)

def run(bucket: str, input_key: str):
    chunks = get_transcript_s3(bucket, input_key)
    meta = extract_metadata_from_key(input_key)
    embedding, full_text = generate_case_embedding(chunks, MODEL_NAME, BATCH_SIZE)
    ensure_index_exists(os_client, INDEX_NAME)
    index_case_embedding_to_opensearch(embedding, full_text, meta, input_key, INDEX_NAME, os_client)

if __name__ == "__main__":
    INPUT_KEY = os.environ["INPUT_KEY"]
    run(BUCKET, INPUT_KEY)