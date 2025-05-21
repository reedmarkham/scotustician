import logging, io, json
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET

import boto3, botocore.exceptions, numpy as np
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch
from transformers import AutoTokenizer

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize S3 and tokenizer
s3 = boto3.client("s3")
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")

def extract_speaker_list(xml_string: str) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(xml_string)
        speakers = {}

        for el in root.findall("utterance"):
            speaker_id = el.attrib.get("speaker_id")
            speaker_name = el.attrib.get("speaker", "Unknown")
            if speaker_id:
                speakers[speaker_id] = speaker_name

        return [{"id": sid, "name": speakers[sid]} for sid in sorted(speakers)]
    except Exception as e:
        logger.warning(f"⚠️ Could not extract speaker list from XML: {e}")
        return []

def get_transcript_s3(bucket: str, key: str) -> str:
    logger.info(f"📥 Downloading transcript from s3://{bucket}/{key}")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.load(obj['Body'])

        # --- Validate expected structure ---
        if "transcript" not in data or "sections" not in data["transcript"]:
            raise ValueError("Missing expected keys: 'transcript.sections'")

        sections = data["transcript"]["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            raise ValueError("Transcript 'sections' is empty or malformed")

        # --- Generate XML ---
        transcript_root = ET.Element("transcript")
        count = 0
        for section in sections:
            for turn in section.get("turns", []):
                speaker = turn.get("speaker", {}).get("name", "Unknown")
                speaker_id = str(turn.get("speaker", {}).get("id", ""))
                for block in turn.get("text_blocks", []):
                    text = block.get("text")
                    if text:
                        utterance_el = ET.SubElement(
                            transcript_root,
                            "utterance",
                            speaker=speaker,
                            speaker_id=speaker_id
                        )
                        utterance_el.text = text
                        count += 1

        if count == 0:
            raise ValueError("No text blocks found in transcript")

        logger.info(f"🧾 Serialized {count} utterances to XML.")
        xml_str_io = io.StringIO()
        ET.ElementTree(transcript_root).write(xml_str_io, encoding="unicode")
        xml_string = xml_str_io.getvalue()

        # --- Upload XML to /xml/<oa_id>.xml ---
        oa_id = key.split("/")[-1].replace(".json", "")
        xml_key = f"xml/{oa_id}.xml"
        s3.put_object(Bucket=bucket, Key=xml_key, Body=xml_string.encode("utf-8"))
        logger.info(f"✅ Saved XML to s3://{bucket}/{xml_key}")

        return xml_string

    except Exception as e:
        logger.error(f"❌ Failed to load or parse {key} from S3: {e}")

        # Upload malformed file to junk/
        try:
            bad_obj = s3.get_object(Bucket=bucket, Key=key)
            bad_data = bad_obj["Body"].read()
            junk_key = f"junk/{key.split('/')[-1]}"
            s3.put_object(Bucket=bucket, Key=junk_key, Body=bad_data)
            logger.warning(f"🚮 Junk file saved to s3://{bucket}/{junk_key}")
        except botocore.exceptions.BotoCoreError as junk_err:
            logger.error(f"⚠️ Could not upload junk file: {junk_err}")

        raise

def truncate_to_tokens(text: str, max_tokens: int = 384) -> str:
    tokens = tokenizer.encode(text, add_special_tokens=False)
    logger.info(f"🧮 Token count before truncation: {len(tokens)}")

    truncated_tokens = tokens[:max_tokens]
    logger.info(f"✂️ Token count after truncation: {len(truncated_tokens)}")

    return tokenizer.decode(truncated_tokens, skip_special_tokens=True)

def generate_case_embedding(
    xml_string: str,
    model_name: str,
    batch_size: int
) -> Tuple[List[float], str]:
    logger.info(f"⚙️ Loading model: {model_name}")
    model = SentenceTransformer(model_name)

    try:
        root = ET.fromstring(xml_string)
        turns = [
            f"{el.attrib.get('speaker', 'Unknown')}: {el.text.strip()}"
            for el in root.findall("utterance")
            if el.text and len(el.text.strip().split()) > 3
        ]

        if not turns:
            raise ValueError("No valid utterances found to embed.")

        logger.info(f"🧠 Generating embeddings for {len(turns)} speaker turns.")
        embeddings = model.encode(turns, batch_size=batch_size, show_progress_bar=True)
        avg_embedding = np.mean(embeddings, axis=0).tolist()
        full_text = "\n".join(turns)

        return avg_embedding, full_text

    except Exception as e:
        logger.error(f"❌ Failed to generate embedding from XML: {e}")
        raise

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
                "source_key": {"type": "keyword"},
                "xml_uri": {"type": "keyword"},
                "speaker_list": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {"type": "keyword"}
                    }
                }
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
    os_client: OpenSearch,
    speaker_list: List[Dict[str, str]]
):
    assert len(embedding) == 384, f"Embedding has invalid dimension: {len(embedding)}"

    bucket_name = "scotustician"
    xml_key = f"xml/{meta['oa_id'].replace('.json', '')}.xml"
    xml_uri = f"s3://{bucket_name}/{xml_key}"

    doc = {
        "vector": embedding,
        "text": full_text,
        "term": meta["term"],
        "case_name": meta["case_name"],
        "case_id": meta["case_id"],
        "oa_id": meta["oa_id"],
        "source_key": source_key,
        "xml_uri": xml_uri,
        "speaker_list": speaker_list
    }

    logger.info(f"📝 Indexing OA: case_id={meta['case_id']}, oa_id={meta['oa_id']}")
    os_client.index(index=index_name, id=meta["oa_id"], body=doc)
