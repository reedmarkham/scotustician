import logging, io, json, os
from typing import List, Dict
import xml.etree.ElementTree as ET

import boto3, botocore.exceptions
from psycopg2.extras import Json
from transformers import AutoTokenizer
from sentence_transformers import SentenceTransformer

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize S3 and tokenizer
s3 = boto3.client("s3")
MODEL_NAME_FOR_TOKENIZER = os.environ.get('MODEL_NAME', 'nvidia/NV-Embed-v2')
# Use the model directly for tokenizer, as NV-Embed-v2 is not in sentence-transformers format
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME_FOR_TOKENIZER)

def get_transcript_s3(bucket: str, key: str) -> str:
    logger.info(f"Downloading transcript from s3://{bucket}/{key}")
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

        logger.info(f"Serialized {count} utterances to XML.")
        xml_str_io = io.StringIO()
        ET.ElementTree(transcript_root).write(xml_str_io, encoding="unicode")
        xml_string = xml_str_io.getvalue()

        # --- Upload XML to /xml/<oa_id>.xml ---
        oa_id = key.split("/")[-1].replace(".json", "")
        xml_key = f"xml/{oa_id}.xml"
        s3.put_object(Bucket=bucket, Key=xml_key, Body=xml_string.encode("utf-8"))
        logger.info(f"Saved XML to s3://{bucket}/{xml_key}")

        return xml_string

    except Exception as e:
        logger.error(f"Failed to load or parse {key} from S3: {e}")

        # Upload malformed file to junk/
        try:
            bad_obj = s3.get_object(Bucket=bucket, Key=key)
            bad_data = bad_obj["Body"].read()
            junk_key = f"junk/{key.split('/')[-1]}"
            s3.put_object(Bucket=bucket, Key=junk_key, Body=bad_data)
            logger.warning(f"Junk file saved to s3://{bucket}/{junk_key}")
        except botocore.exceptions.BotoCoreError as junk_err:
            logger.error(f"Could not upload junk file: {junk_err}")

        raise

def truncate_to_tokens(text: str, max_tokens: int = 4096) -> str:
    tokens = tokenizer.encode(text, add_special_tokens=False)
    logger.info(f"Token count before truncation: {len(tokens)}")

    truncated_tokens = tokens[:max_tokens]
    logger.info(f"Token count after truncation: {len(truncated_tokens)}")

    return tokenizer.decode(truncated_tokens, skip_special_tokens=True)

def generate_utterance_embeddings(
    xml_string: str,
    model_name: str,
    model_dimension: int,
    batch_size: int
) -> List[Dict]:
    """Generate embeddings for individual utterances with metadata."""
    logger.info(f"Loading model: {model_name}")
    model = SentenceTransformer(model_name)

    try:
        root = ET.fromstring(xml_string)
        utterances = []
        texts_to_embed = []
        char_offset = 0
        
        for idx, el in enumerate(root.findall("utterance")):
            if el.text and len(el.text.strip().split()) > 3:
                speaker_id = el.attrib.get('speaker_id', '')
                speaker_name = el.attrib.get('speaker', 'Unknown')
                text = el.text.strip()
                full_text = f"{speaker_name}: {text}"
                
                # Get timing info if available
                start_time = el.attrib.get('start_time_ms')
                end_time = el.attrib.get('end_time_ms')
                
                # Calculate token count for the text
                token_count = len(tokenizer.encode(text, add_special_tokens=False))
                
                utterances.append({
                    'utterance_index': idx,
                    'speaker_id': speaker_id,
                    'speaker_name': speaker_name,
                    'text': text,
                    'full_text': full_text,
                    'word_count': len(text.split()),
                    'token_count': token_count,
                    'char_start_offset': char_offset,
                    'char_end_offset': char_offset + len(text),
                    'start_time_ms': int(start_time) if start_time else None,
                    'end_time_ms': int(end_time) if end_time else None,
                    'embedding_model': model_name,
                    'embedding_dimension': model_dimension
                })
                texts_to_embed.append(full_text)
                char_offset += len(text) + 1  # +1 for space between utterances

        if not utterances:
            raise ValueError("No valid utterances found to embed.")

        logger.info(f"Generating embeddings for {len(utterances)} utterances.")
        embeddings = model.encode(texts_to_embed, batch_size=batch_size, show_progress_bar=True)
        
        # Add embeddings to utterance data
        for utt, emb in zip(utterances, embeddings):
            utt['embedding'] = emb.tolist()
            
        return utterances

    except Exception as e:
        logger.error(f"Failed to generate utterance embeddings from XML: {e}")
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
    logger.info("Ensuring Postgres tables exist...")
    
    # Get the path to the SQL file
    sql_file_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    
    # Read and execute the SQL file
    with open(sql_file_path, 'r') as sql_file:
        sql_content = sql_file.read()
    
    with conn.cursor() as cur:
        cur.execute(sql_content)
        conn.commit()
    
    logger.info("Tables exist.")

def insert_utterance_embeddings_to_postgres(
    utterances: List[Dict],
    meta: Dict[str, str],
    source_key: str,
    conn
):
    with conn.cursor() as cur:
        for utt in utterances:
            expected_dim = utt.get('embedding_dimension', 384)
            assert len(utt['embedding']) == expected_dim, f"Embedding has invalid dimension: {len(utt['embedding'])}, expected {expected_dim}"
            
            cur.execute("""
                INSERT INTO scotustician.utterance_embeddings 
                (case_id, oa_id, utterance_index, speaker_id, speaker_name, 
                 text, vector, word_count, source_key, token_count,
                 char_start_offset, char_end_offset, start_time_ms, end_time_ms,
                 embedding_model, embedding_dimension)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id, utterance_index) 
                DO UPDATE SET
                    speaker_id = EXCLUDED.speaker_id,
                    speaker_name = EXCLUDED.speaker_name,
                    text = EXCLUDED.text,
                    vector = EXCLUDED.vector,
                    word_count = EXCLUDED.word_count,
                    source_key = EXCLUDED.source_key,
                    token_count = EXCLUDED.token_count,
                    char_start_offset = EXCLUDED.char_start_offset,
                    char_end_offset = EXCLUDED.char_end_offset,
                    start_time_ms = EXCLUDED.start_time_ms,
                    end_time_ms = EXCLUDED.end_time_ms,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dimension = EXCLUDED.embedding_dimension
            """, (
                meta["case_id"],
                meta["oa_id"],
                utt['utterance_index'],
                utt['speaker_id'],
                utt['speaker_name'],
                utt['text'],
                utt['embedding'],
                utt['word_count'],
                source_key,
                utt.get('token_count'),
                utt.get('char_start_offset'),
                utt.get('char_end_offset'),
                utt.get('start_time_ms'),
                utt.get('end_time_ms'),
                utt.get('embedding_model'),
                utt.get('embedding_dimension')
            ))
        
        conn.commit()
    
    logger.info(f"Inserted {len(utterances)} utterance embeddings for case_id={meta['case_id']}")
