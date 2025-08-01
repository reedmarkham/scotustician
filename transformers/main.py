import os

import psycopg2
from helpers import (
    get_transcript_s3,
    generate_utterance_embeddings,
    extract_metadata_from_key,
    ensure_tables_exist,
    insert_utterance_embeddings_to_postgres
)

BUCKET = os.getenv("S3_BUCKET", "scotustician")
INDEX_NAME = os.getenv("INDEX_NAME", "scotus-oa-embeddings")
MODEL_NAME = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 16))

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS", ""),
        database=os.getenv("POSTGRES_DB", "scotustician")
    )

def run(bucket: str, input_key: str):
    xml_string = get_transcript_s3(bucket, input_key)
    meta = extract_metadata_from_key(input_key)
    
    utterances = generate_utterance_embeddings(xml_string, MODEL_NAME, BATCH_SIZE)
    
    with get_db_connection() as conn:
        ensure_tables_exist(conn)
        insert_utterance_embeddings_to_postgres(
            utterances, meta, input_key, conn
        )


if __name__ == "__main__":
    INPUT_KEY = os.environ["INPUT_KEY"]
    run(BUCKET, INPUT_KEY)