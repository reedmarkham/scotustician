import os

from helpers import (
    get_transcript_s3,
    generate_utterance_embeddings,
    generate_utterance_embeddings_incremental,
    extract_metadata_from_key,
    ensure_tables_exist,
    insert_utterance_embeddings_to_postgres
)

import psycopg2

BUCKET = os.getenv("S3_BUCKET", "scotustician")
MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 4))

# Validate model dimension for pgvector compatibility
if MODEL_DIMENSION > 2000:
    raise ValueError(f"Model dimension {MODEL_DIMENSION} exceeds pgvector maximum of 2000. Please set MODEL_DIMENSION to 2000 or less.")

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS", ""),
        database=os.getenv("POSTGRES_DB", "scotustician")
    )

def run(bucket: str, input_key: str, incremental: bool = True):
    xml_string = get_transcript_s3(bucket, input_key)
    meta = extract_metadata_from_key(input_key)
    
    with get_db_connection() as conn:
        ensure_tables_exist(conn)
        
        if incremental:
            # Use incremental approach
            utterances = generate_utterance_embeddings_incremental(
                xml_string, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, 
                meta["case_id"], conn
            )
        else:
            # Use full regeneration approach
            utterances = generate_utterance_embeddings(
                xml_string, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE
            )
        
        if utterances:  # Only insert if there are new utterances
            insert_utterance_embeddings_to_postgres(
                utterances, meta, input_key, conn
            )


if __name__ == "__main__":
    INPUT_KEY = os.environ["INPUT_KEY"]
    INCREMENTAL = os.getenv("INCREMENTAL", "true").lower() == "true"
    run(BUCKET, INPUT_KEY, incremental=INCREMENTAL)