import logging, io, json, os, time, threading, signal
from typing import List, Dict
import xml.etree.ElementTree as ET

# Disable tokenizers parallelism to avoid warnings in multi-threaded environment
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import psycopg2, boto3, botocore.exceptions
from tqdm import tqdm
from transformers import AutoTokenizer
from sentence_transformers import SentenceTransformer

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize S3 and tokenizer
s3 = boto3.client("s3")
MODEL_NAME = os.environ.get('MODEL_NAME', 'baai/bge-m3')
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

# Global shutdown flag for graceful shutdown handling
shutdown_requested = threading.Event()
active_futures = set()
executor_lock = threading.Lock()

def save_processing_checkpoint(processed_keys: set, checkpoint_file: str = "/tmp/scotustician_checkpoint.json"):
    """Save processing checkpoint to allow resumption after interruption"""
    try:
        import json
        checkpoint_data = {
            'processed_keys': list(processed_keys),
            'timestamp': time.time()
        }
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f)
        logger.debug(f"Checkpoint saved with {len(processed_keys)} processed keys")
    except Exception as e:
        logger.warning(f"Failed to save checkpoint: {e}")

def load_processing_checkpoint(checkpoint_file: str = "/tmp/scotustician_checkpoint.json") -> set:
    """Load processing checkpoint to resume from where we left off"""
    try:
        import json
        import time
        with open(checkpoint_file, 'r') as f:
            checkpoint_data = json.load(f)
        
        # Only use checkpoint if it's less than 24 hours old
        if time.time() - checkpoint_data.get('timestamp', 0) < 86400:
            processed_keys = set(checkpoint_data.get('processed_keys', []))
            logger.info(f"Loaded checkpoint with {len(processed_keys)} processed keys")
            return processed_keys
        else:
            logger.info("Checkpoint too old, starting fresh")
            return set()
    except Exception as e:
        logger.debug(f"No valid checkpoint found: {e}")
        return set()

def get_transcript_s3(bucket: str, key: str) -> str:
    logger.info(f"Downloading transcript from s3://{bucket}/{key}")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.load(obj['Body'])

        # Data validation
        if "transcript" not in data or "sections" not in data["transcript"]:
            raise ValueError("Missing expected keys: 'transcript.sections'")

        sections = data["transcript"]["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            raise ValueError("Transcript 'sections' is empty or malformed")

        # Generate XML
        transcript_root = ET.Element("transcript")
        count = 0
        # Count total text blocks for progress bar
        total_blocks = sum(
            len(turn.get("text_blocks", []))
            for section in sections
            for turn in section.get("turns", [])
        )
        
        with tqdm(total=total_blocks, desc="Converting to XML", unit="blocks", 
                 disable=shutdown_requested.is_set()) as pbar:
            for section in sections:
                if shutdown_requested.is_set():
                    logger.info("Shutdown requested during XML conversion")
                    raise InterruptedError("Processing interrupted during XML conversion")
                
                for turn in section.get("turns", []):
                    if shutdown_requested.is_set():
                        logger.info("Shutdown requested during turn processing")
                        raise InterruptedError("Processing interrupted during turn processing")
                        
                    speaker = turn.get("speaker", {}).get("name", "Unknown")
                    for block in turn.get("text_blocks", []):
                        text = block.get("text")
                        if text:
                            utterance_el = ET.SubElement(
                                transcript_root,
                                "utterance",
                                speaker=speaker
                            )
                            utterance_el.text = text
                            count += 1
                        pbar.update(1)

        if count == 0:
            raise ValueError("No text blocks found in transcript")

        logger.info(f"Serialized {count} utterances to XML.")
        xml_str_io = io.StringIO()
        ET.ElementTree(transcript_root).write(xml_str_io, encoding="unicode")
        xml_string = xml_str_io.getvalue()

        # Upload XML to /xml/<oa_id>.xml
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

def process_transcript_with_chunking(
    bucket: str,
    key: str,
    model_name: str,
    model_dimension: int,
    batch_size: int,
    conn,
    meta: Dict[str, str]
) -> List[Dict]:
    """
    Section-based chunking approach:
    1. Stores raw utterance data to oa_text table
    2. Creates chunks based on JSON sections
    3. Each section becomes a chunk (with section_id = array index)
    4. Generates embeddings for each section
    """
    logger.info(f"Processing transcript from s3://{bucket}/{key}")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.load(obj['Body'])

        # Data validation
        if "transcript" not in data or "sections" not in data["transcript"]:
            raise ValueError("Missing expected keys: 'transcript.sections'")

        sections = data["transcript"]["sections"]
        if not isinstance(sections, list) or len(sections) == 0:
            raise ValueError("Transcript 'sections' is empty or malformed")

        # Process by OA section (petitioner, respondent, rebuttal) for document chunking
        all_utterances_data = []
        section_chunks = []
        global_utterance_idx = 0
        global_char_offset = 0

        logger.info(f"Processing {len(sections)} sections...")
        
        for section_id, section in enumerate(sections):
            if shutdown_requested.is_set():
                logger.info(f"Shutdown requested during section {section_id} processing")
                raise InterruptedError(f"Processing interrupted at section {section_id}")
                
            section_utterances = []
            section_texts = []
            start_utterance_idx = global_utterance_idx
            
            # Process all turns in this section
            for turn in section.get("turns", []):
                if shutdown_requested.is_set():
                    logger.info(f"Shutdown requested during turn processing in section {section_id}")
                    raise InterruptedError(f"Processing interrupted during turn in section {section_id}")
                    
                speaker = turn.get("speaker", {}).get("name", "Unknown")
                speaker_id = str(turn.get("speaker", {}).get("id", ""))
                
                for block in turn.get("text_blocks", []):
                    text = block.get("text")
                    if text and len(text.strip().split()) > 3:
                        text = text.strip()
                        
                        # Collect full metadata for oa_text table
                        token_count = len(tokenizer.encode(text, add_special_tokens=False))
                        
                        utterance_data = {
                            'case_id': meta["case_id"],
                            'oa_id': meta["oa_id"],
                            'utterance_index': global_utterance_idx,
                            'speaker_id': speaker_id,
                            'speaker_name': speaker,
                            'text': text,
                            'word_count': len(text.split()),
                            'token_count': token_count,
                            'char_start_offset': global_char_offset,
                            'char_end_offset': global_char_offset + len(text),
                            'start_time_ms': block.get('start_time_ms'),
                            'end_time_ms': block.get('end_time_ms'),
                            'source_key': key
                        }
                        
                        all_utterances_data.append(utterance_data)
                        section_utterances.append(utterance_data)
                        section_texts.append(f"{speaker}: {text}")
                        
                        global_char_offset += len(text) + 1
                        global_utterance_idx += 1
            
            # Create chunk for this section if it has content
            if section_texts:
                chunk_text = "\n".join(section_texts)
                token_count = len(tokenizer.encode(chunk_text, add_special_tokens=False))
                
                # Truncate if exceeds max tokens
                if token_count > 8000:
                    logger.warning(f"Section {section_id} exceeds 8000 tokens ({token_count}), truncating...")
                    chunk_text = truncate_to_tokens(chunk_text, 8000)
                    token_count = 8000
                
                section_chunk = {
                    'section_id': section_id,
                    'chunk_text': chunk_text,
                    'word_count': len(chunk_text.split()),
                    'token_count': token_count,
                    'start_utterance_index': start_utterance_idx,
                    'end_utterance_index': global_utterance_idx - 1,
                    'utterance_count': len(section_utterances)
                }
                
                section_chunks.append(section_chunk)
                logger.info(f"Created chunk for section {section_id}: {len(section_utterances)} utterances, {token_count} tokens")

        if not all_utterances_data:
            raise ValueError("No valid utterances found in transcript")

        logger.info(f"Processed {len(all_utterances_data)} total utterances across {len(section_chunks)} sections.")
        
        if shutdown_requested.is_set():
            logger.info("Shutdown requested before database insert")
            raise InterruptedError("Processing interrupted before database insert")
            
        insert_oa_text_data(all_utterances_data, conn)
        
        if shutdown_requested.is_set():
            logger.info("Shutdown requested before embedding generation")
            raise InterruptedError("Processing interrupted before embedding generation")
        
        logger.info(f"Generating embeddings for {len(section_chunks)} section chunks...")
        model = SentenceTransformer(model_name)
        model.eval()
        
        chunk_texts = [chunk['chunk_text'] for chunk in section_chunks]
        
        # Check for interruption before the expensive embedding generation
        if shutdown_requested.is_set():
            logger.info("Shutdown requested during embedding model preparation")
            raise InterruptedError("Processing interrupted during embedding model preparation")
        
        embeddings = model.encode(
            chunk_texts, 
            batch_size=batch_size, 
            show_progress_bar=not shutdown_requested.is_set(), 
            convert_to_tensor=False
        )
        
        if shutdown_requested.is_set():
            logger.info("Shutdown requested after embedding generation")
            raise InterruptedError("Processing interrupted after embedding generation")
        
        # Add embeddings and metadata to chunks
        for chunk, emb in zip(section_chunks, embeddings):
            chunk.update({
                'case_id': meta["case_id"],
                'oa_id': meta["oa_id"],
                'vector': emb.tolist(),
                'embedding_model': model_name,
                'embedding_dimension': model_dimension,
                'source_key': key
            })

        return section_chunks

    except Exception as e:
        logger.error(f"Failed to process transcript {key}: {e}")
        
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


def process_single_document(bucket: str, input_key: str, model_name: str, model_dimension: int, batch_size: int):
    meta = extract_metadata_from_key(input_key)
    
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASS", ""),
        database=os.getenv("POSTGRES_DB", "scotustician")
    )
    
    try:
        ensure_tables_exist(conn)
        
        # Use section-based chunking approach
        chunks = process_transcript_with_chunking(
            bucket, input_key, model_name, model_dimension, batch_size, conn, meta
        )
        
        insert_document_chunk_embeddings(chunks, conn)
        
        logger.info(f"Successfully processed single document: {input_key}")
    finally:
        conn.close()

def truncate_to_tokens(text: str, max_tokens: int = 8000) -> str:
    """Truncate text to specified token limit"""
    tokens = tokenizer.encode(text, add_special_tokens=False)
    if len(tokens) <= max_tokens:
        return text
        
    logger.info(f"Truncating from {len(tokens)} to {max_tokens} tokens")
    truncated_tokens = tokens[:max_tokens]
    return tokenizer.decode(truncated_tokens, skip_special_tokens=True)

def insert_oa_text_data(utterances_data: List[Dict], conn):
    logger.info(f"Inserting {len(utterances_data)} utterances to oa_text table")
    
    with conn.cursor() as cur:
        for utt in tqdm(utterances_data, desc="Inserting to oa_text"):
            cur.execute("""
                INSERT INTO scotustician.oa_text 
                (case_id, oa_id, utterance_index, speaker_id, speaker_name, 
                 text, word_count, token_count, start_time_ms, end_time_ms,
                 char_start_offset, char_end_offset, source_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id, utterance_index) 
                DO UPDATE SET
                    speaker_id = EXCLUDED.speaker_id,
                    speaker_name = EXCLUDED.speaker_name,
                    text = EXCLUDED.text,
                    word_count = EXCLUDED.word_count,
                    token_count = EXCLUDED.token_count,
                    start_time_ms = EXCLUDED.start_time_ms,
                    end_time_ms = EXCLUDED.end_time_ms,
                    char_start_offset = EXCLUDED.char_start_offset,
                    char_end_offset = EXCLUDED.char_end_offset,
                    source_key = EXCLUDED.source_key
            """, (
                utt['case_id'],
                utt['oa_id'], 
                utt['utterance_index'],
                utt.get('speaker_id'),
                utt['speaker_name'],
                utt['text'],
                utt['word_count'],
                utt['token_count'],
                utt.get('start_time_ms'),
                utt.get('end_time_ms'),
                utt.get('char_start_offset'),
                utt.get('char_end_offset'),
                utt['source_key']
            ))
        
        conn.commit()
    
    logger.info(f"Successfully inserted {len(utterances_data)} utterances")

def insert_document_chunk_embeddings(chunks: List[Dict], conn):
    logger.info(f"Inserting {len(chunks)} section-based chunk embeddings")
    
    with conn.cursor() as cur:
        for chunk in chunks:
            expected_dim = chunk.get('embedding_dimension', 1024)
            assert len(chunk['vector']) == expected_dim, f"Embedding has invalid dimension: {len(chunk['vector'])}, expected {expected_dim}"
            
            cur.execute("""
                INSERT INTO scotustician.document_chunk_embeddings 
                (case_id, oa_id, section_id, chunk_text, vector, word_count, 
                 token_count, start_utterance_index, end_utterance_index, 
                 embedding_model, embedding_dimension, source_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id, section_id) 
                DO UPDATE SET
                    chunk_text = EXCLUDED.chunk_text,
                    vector = EXCLUDED.vector,
                    word_count = EXCLUDED.word_count,
                    token_count = EXCLUDED.token_count,
                    start_utterance_index = EXCLUDED.start_utterance_index,
                    end_utterance_index = EXCLUDED.end_utterance_index,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dimension = EXCLUDED.embedding_dimension,
                    source_key = EXCLUDED.source_key
            """, (
                chunk['case_id'],
                chunk['oa_id'],
                chunk['section_id'],
                chunk['chunk_text'],
                chunk['vector'],
                chunk['word_count'],
                chunk['token_count'],
                chunk['start_utterance_index'],
                chunk['end_utterance_index'],
                chunk['embedding_model'],
                chunk['embedding_dimension'],
                chunk['source_key']
            ))
        
        conn.commit()
    
    logger.info(f"Successfully inserted {len(chunks)} section-based embeddings")


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

def signal_handler(signum, frame):
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested.set()

def setup_signal_handlers():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal handlers configured for graceful shutdown")

def get_db_connection():
    POSTGRES_HOST = os.getenv("POSTGRES_HOST")
    POSTGRES_USER = os.getenv("POSTGRES_USER")
    POSTGRES_PASS = os.getenv("POSTGRES_PASS")
    POSTGRES_DB = os.getenv("POSTGRES_DB")
    
    if not all([POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASS, POSTGRES_DB]):
        raise EnvironmentError("Missing required Postgres environment variables")
    
    return psycopg2.connect(
        host=POSTGRES_HOST,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
        database=POSTGRES_DB
    )

def get_processed_keys():
    processed_keys = set()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT s3_key 
                    FROM scotustician.transcript_embeddings 
                    WHERE s3_key IS NOT NULL
                """)
                processed_keys = {row[0] for row in cursor.fetchall()}
                logger.info(f"Found {len(processed_keys)} already processed files in database")
    except Exception as e:
        logger.warning(f"Could not fetch processed keys from database: {e}")
    return processed_keys

def list_s3_keys(bucket: str, prefix: str):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    logger.info(f"Listing objects in s3://{bucket}/{prefix}...")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if shutdown_requested.is_set():
            logger.info("Shutdown requested during S3 listing, stopping...")
            break
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    
    INCREMENTAL = os.getenv("INCREMENTAL", "true").lower() == "true"
    if INCREMENTAL:
        processed_keys = get_processed_keys()
        initial_count = len(keys)
        keys = [k for k in keys if k not in processed_keys]
        logger.info(f"Incremental mode: filtered {initial_count - len(keys)} already processed files")
    
    logger.info(f"Found {len(keys)} objects to process")
    return keys

def process_key(key: str):
    """Process a single key with interruption checking"""
    if shutdown_requested.is_set():
        return f"Skipped: {key} (shutdown requested)"
    
    BUCKET = os.getenv("S3_BUCKET", "scotustician")
    MODEL_NAME = os.getenv("MODEL_NAME", "baai/bge-m3")
    MODEL_DIMENSION = int(os.getenv("MODEL_DIMENSION", 1024))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 24))
    
    try:
        meta = extract_metadata_from_key(key)
        
        if shutdown_requested.is_set():
            return f"Interrupted: {key} (shutdown during processing)"
        
        with get_db_connection() as conn:
            chunks = process_transcript_with_chunking(
                BUCKET, key, MODEL_NAME, MODEL_DIMENSION, BATCH_SIZE, conn, meta
            )
            
            if shutdown_requested.is_set():
                logger.warning(f"Shutdown requested during chunking for {key}")
                return f"Interrupted: {key} (shutdown during chunking)"
            
            insert_document_chunk_embeddings(chunks, conn)

        if shutdown_requested.is_set():
            return f"Interrupted: {key} (shutdown after processing)"
        
        return f"Processed: {key} ({len(chunks)} section chunks created)"
    except Exception as e:
        if shutdown_requested.is_set():
            return f"Interrupted: {key} | {e}"
        return f"Failed: {key} | {e}"

def graceful_shutdown_executor(executor, timeout=30):
    """Gracefully shutdown ThreadPoolExecutor with timeout"""
    logger.info(f"Initiating graceful shutdown of executor (timeout: {timeout}s)...")
    
    # Cancel pending futures
    cancelled_count = 0
    with executor_lock:
        for future in list(active_futures):
            if future.cancel():
                cancelled_count += 1
    
    logger.info(f"Cancelled {cancelled_count} pending tasks")
    
    executor.shutdown(wait=False)
    
    # Wait for running tasks to complete with timeout
    start_time = time.time()
    while time.time() - start_time < timeout:
        with executor_lock:
            running_futures = [f for f in active_futures if f.running()]
        if not running_futures:
            logger.info("All running tasks completed gracefully")
            return True
        time.sleep(0.5)
    
    logger.warning(f"Timeout reached, {len(running_futures)} tasks may still be running")
    return False

def ensure_tables_exist(conn):
    logger.info("Ensuring Postgres tables exist...")
    
    sql_file_path = os.path.join(os.path.dirname(__file__), 'schema.sql')

    with open(sql_file_path, 'r') as sql_file:
        sql_content = sql_file.read()
    
    with conn.cursor() as cur:
        cur.execute(sql_content)
        conn.commit()
    
    logger.info("Tables exist.")

