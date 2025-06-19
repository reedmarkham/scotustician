import logging, io, json
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET

import boto3, botocore.exceptions, numpy as np
from sentence_transformers import SentenceTransformer
import psycopg2
from psycopg2.extras import Json
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

def ensure_tables_exist(conn):
    logger.info("📚 Ensuring Postgres tables exist...")
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scotustician.transcript_embeddings (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                vector vector(384),
                case_name VARCHAR(255),
                term VARCHAR(10),
                case_id VARCHAR(255) NOT NULL,
                oa_id VARCHAR(255),
                source_key VARCHAR(500),
                xml_uri VARCHAR(500),
                speaker_list JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scotustician.raw_transcripts (
                id SERIAL PRIMARY KEY,
                case_id VARCHAR(255) NOT NULL,
                s3_key VARCHAR(500) NOT NULL,
                raw_data JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    logger.info("✅ Tables ensured.")

def insert_case_embedding_to_postgres(
    embedding: List[float],
    full_text: str,
    meta: Dict[str, str],
    source_key: str,
    conn,
    speaker_list: List[Dict[str, str]]
):
    assert len(embedding) == 384, f"Embedding has invalid dimension: {len(embedding)}"

    bucket_name = "scotustician"
    xml_key = f"xml/{meta['oa_id'].replace('.json', '')}.xml"
    xml_uri = f"s3://{bucket_name}/{xml_key}"

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scotustician.transcript_embeddings 
            (text, vector, case_name, term, case_id, oa_id, source_key, xml_uri, speaker_list)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            full_text,
            embedding,
            meta["case_name"],
            meta["term"],
            meta["case_id"],
            meta["oa_id"],
            source_key,
            xml_uri,
            Json(speaker_list)
        ))
        conn.commit()

    logger.info(f"📝 Inserted/Updated OA: case_id={meta['case_id']}, oa_id={meta['oa_id']}")
