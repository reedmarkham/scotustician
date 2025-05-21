import logging
from typing import List, Tuple, Dict

import boto3
import pandas as pd
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch

s3 = boto3.client("s3")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def get_transcript_s3(bucket: str, key: str) -> List[str]:
    logger.info(f"📥 Downloading transcript from s3://{bucket}/{key}")
    obj = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_json(obj['Body'], lines=True)
    return df['text'].tolist()

def generate_case_embedding(
    chunks: List[str],
    model_name: str,
    batch_size: int
) -> Tuple[List[float], str]:
    logger.info(f"⚙️ Loading model: {model_name}")
    model = SentenceTransformer(model_name)
    full_text = " ".join(chunks)[:2048]  # naive truncation
    logger.info(f"🧠 Generating embedding for full oral argument text.")
    embedding = model.encode([full_text], batch_size=batch_size, show_progress_bar=False)[0]
    return embedding.tolist(), full_text

def extract_metadata_from_key(key: str) -> Dict[str, str]:
    filename = key.split("/")[-1].replace(".json", "")
    oa_id = filename + ".json"
    
    if "_" in filename:
        term, case_name = filename.split("_", 1)
    else:
        term, case_name = "unknown", filename

    case_id = f"{term}_{case_name}"
    return {
        "term": term,
        "case_name": case_name,
        "case_id": case_id,
        "oa_id": oa_id,
    }

def ensure_index_exists(os_client: OpenSearch, index_name: str):
    if os_client.indices.exists(index=index_name):
        return
    logger.info(f"📚 Creating OpenSearch index '{index_name}'...")
    os_client.indices.create(index=index_name, body={
        "mappings": {
            "properties": {
                "text": {"type": "text"},
                "vector": {
                "type": "dense_vector",
                "dims": 384,
                "index": True,
                "similarity": "cosine"
                },
                "case_name": {"type": "keyword"},
                "term": {"type": "keyword"},
                "case_id": {"type": "keyword"},
                "oa_id": {"type": "keyword"},
                "source_key": {"type": "keyword"}
            }
        }
    })

def index_case_embedding_to_opensearch(
    embedding: List[float],
    full_text: str,
    meta: Dict[str, str],
    source_key: str,
    index_name: str,
    os_client: OpenSearch
):
    doc = {
        "vector": embedding,
        "text": full_text,
        "term": meta["term"],
        "case_name": meta["case_name"],
        "case_id": meta["case_id"],
        "oa_id": meta["oa_id"],
        "source_key": source_key
    }

    logger.info(f"📝 Indexing OA: case_id={meta['case_id']}, oa_id={meta['oa_id']}")
    os_client.index(index=index_name, id=meta["oa_id"], body=doc)
