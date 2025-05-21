import logging
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET
import io

import boto3
import pandas as pd
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch
from transformers import AutoTokenizer

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize S3 and tokenizer
s3 = boto3.client("s3")
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")

def get_transcript_s3(bucket: str, key: str) -> str:
    logger.info(f"📥 Downloading transcript from s3://{bucket}/{key}")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = pd.read_json(obj['Body'])

        sections = data["transcript"]["sections"]
        transcript_root = ET.Element("transcript")

        count = 0
        for section in sections:
            for turn in section.get("turns", []):
                speaker = turn.get("speaker", {}).get("name", "Unknown")
                for block in turn.get("text_blocks", []):
                    text = block.get("text")
                    if text:
                        utterance_el = ET.SubElement(transcript_root, "utterance", speaker=speaker)
                        utterance_el.text = text
                        count += 1

        logger.info(f"🧾 Serialized {count} utterances to XML.")
        xml_str_io = io.StringIO()
        ET.ElementTree(transcript_root).write(xml_str_io, encoding="unicode")
        return xml_str_io.getvalue()

    except Exception as e:
        logger.error(f"❌ Failed to load {key} from S3: {e}")
        raise

def truncate_to_tokens(text: str, max_tokens: int = 384) -> str:
    tokens = tokenizer.encode(text, add_special_tokens=False)
    logger.info(f"🧮 Token count before truncation: {len(tokens)}")

    truncated_tokens = tokens[:max_tokens]
    logger.info(f"✂️ Token count after truncation: {len(truncated_tokens)}")

    return tokenizer.decode(truncated_tokens, skip_special_tokens=True)

def generate_case_embedding(
    chunks: List[str],
    model_name: str,
    batch_size: int
) -> Tuple[List[float], str]:
    logger.info(f"⚙️ Loading model: {model_name}")
    model = SentenceTransformer(model_name)

    raw_text = " ".join(chunks)
    truncated_text = truncate_to_tokens(raw_text, max_tokens=384)

    logger.info(f"🧠 Generating embedding for truncated oral argument text.")
    embedding = model.encode([truncated_text], batch_size=batch_size, show_progress_bar=False)[0]
    return embedding.tolist(), truncated_text

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
                    "type": "knn_vector",
                    "dimension": 384,
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
    logger.info(f"✅ Index '{index_name}' created.")

def index_case_embedding_to_opensearch(
    embedding: List[float],
    full_text: str,
    meta: Dict[str, str],
    source_key: str,
    index_name: str,
    os_client: OpenSearch
):
    assert len(embedding) == 384, f"Embedding has invalid dimension: {len(embedding)}"

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
