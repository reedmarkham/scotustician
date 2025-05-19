import logging
import boto3
import torch
import pandas as pd
from typing import List
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch

s3 = boto3.client("s3")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_transcript_s3(bucket: str, key: str) -> List[str]:
    logger.info(f"📥 Downloading transcript from s3://{bucket}/{key}")
    obj = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_json(obj['Body'], lines=True)
    return df['text'].tolist()

def generate_embeddings(
    chunks: List[str],
    model_name: str = "all-MiniLM-L6-v2",
    batch_size: int = 16
) -> List[List[float]]:
    logger.info(f"⚙️ Loading model: {model_name}")
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    logger.info(f"🧠 Using device: {device}")

    model = SentenceTransformer(model_name, device=device)
    logger.info(f"📦 Generating embeddings in batches of {batch_size}")

    with torch.no_grad():
        embeddings = model.encode(
            chunks,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=True
        )

    logger.info("✅ Embedding generation complete")
    return embeddings.tolist()

def save_embeddings(embeddings: List[List[float]], chunks: List[str], bucket: str, key: str, metadata: dict):
    logger.info(f"💾 Saving embeddings to s3://{bucket}/{key}")
    df = pd.DataFrame({
        "vector": embeddings,
        "text": chunks,
        "term": metadata["term"],
        "case_name": metadata["case_name"],
        "case_id": metadata["case_id"],
        "source_key": key
    })
    s3.put_object(Bucket=bucket, Key=key, Body=df.to_json(orient='records', lines=True))

def ensure_index(os_client: OpenSearch, index_name: str):
    if os_client.indices.exists(index=index_name):
        logger.info(f"📚 Index '{index_name}' already exists.")
        return

    logger.info(f"📚 Creating index '{index_name}' with mapping.")
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
                "source_key": {"type": "keyword"}
            }
        }
    })

def extract_metadata_from_key(key: str) -> dict:
    filename = key.split("/")[-1].replace(".json", "")
    if "_" in filename:
        term, case_name = filename.split("_", 1)
    else:
        term, case_name = "unknown", "unknown"
    case_id = f"{term}_{case_name}"
    return {"term": term, "case_name": case_name, "case_id": case_id}

def index_to_opensearch(
    embeddings: List[List[float]],
    chunks: List[str],
    index_name: str,
    os_client: OpenSearch,
    source_key: str
):
    ensure_index(os_client, index_name)
    meta = extract_metadata_from_key(source_key)

    logger.info(f"📝 Indexing {len(embeddings)} documents into OpenSearch index '{index_name}'")

    bulk_body = []
    for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        doc_id = f"{meta['case_id']}-chunk-{i}"
        bulk_body.append({"index": {"_index": index_name, "_id": doc_id}})
        bulk_body.append({
            "text": chunk,
            "vector": vector,
            "term": meta["term"],
            "case_name": meta["case_name"],
            "case_id": meta["case_id"],
            "source_key": source_key
        })

    response = os_client.bulk(body=bulk_body)
    if response.get("errors"):
        logger.error("⚠️ Errors occurred during bulk indexing.")
    else:
        logger.info("✅ Successfully indexed all documents.")
