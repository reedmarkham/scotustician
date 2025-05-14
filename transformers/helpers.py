# Standard library imports
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

# Third party library imports
import boto3
import aioboto3
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, helpers

CLUSTER_URL = ''
MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def get_client(
    cluster_url: str = CLUSTER_URL,
    username: str = 'admin',
    password: str = 'admin'
) -> OpenSearch:
    client = OpenSearch(
        hosts=[cluster_url],
        http_auth=(username, password),
        verify_certs=False
    )
    return client

OS_CLIENT = get_client()

def count_oa(bucket: str) -> int:
    bucket = boto3.resource('s3').Bucket(bucket)
    n = 0
    for _ in bucket.objects.all():
        n += 1
    return n

async def fetch_and_embed_transcript(
    s3: Any,
    key: str,
    bucket: str,
    model: SentenceTransformer,
    loop: asyncio.AbstractEventLoop,
    executor: ThreadPoolExecutor
) -> List[Dict[str, Any]]:
        obj = await s3.get_object(Bucket=bucket, Key=key)
        o = await obj['Body'].read()
        j = json.loads(o.decode('utf-8'))
        transcript = []
        for s in j['transcript']['sections']:
            for t in s['turns']:
                speaker = t['speaker']['name'] if t['speaker'] else 'None'
                role = 'petitioner' if t['speaker'] and t['speaker']['roles'] is None else 'justice'
                for tb in t['text_blocks']:
                    text = tb['text']
                    start = tb['start']
                    stop = tb['stop']
                    # Run embedding in thread pool
                    embedding = await loop.run_in_executor(executor, model.encode, text, True)
                    utterance = {
                        'oa_id': j['id'],
                        'speaker': speaker,
                        'role': role,
                        'text': text,
                        'embedding': embedding[0],
                        'embedding_dim': embedding[0].shape[0],
                        'start': start,
                        'stop': stop
                    }
                    transcript.append(utterance)
        return transcript

async def get_transcripts_embeddings_async(
    n_transcripts: int,
    bucket: str
) -> List[List[Dict[str, Any]]]:
        session = aioboto3.Session()
        model = MODEL  # Use the global model
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor()
        transcripts = []
        async with session.client('s3') as s3:
            paginator = await s3.get_paginator("list_objects_v2")
            keys = []
            async for page in paginator.paginate(Bucket=bucket, PaginationConfig={'MaxItems': n_transcripts}):
                for c in page["Contents"]:
                    keys.append(c['Key'])
            tasks = [
                fetch_and_embed_transcript(s3, key, bucket, model, loop, executor)
                for key in keys
            ]
            transcripts = await asyncio.gather(*tasks)
        return transcripts

def create_os_index(
    embedding_dim: int,
    index_name: str
) -> None:
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100
                }
            },
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": embedding_dim,
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "nmslib",
                            "parameters": {
                            "ef_construction": 128,
                            "m": 24
                            }
                        }
                    }
                }
            }
        }

        OS_CLIENT.indices.create(index=index_name, body=index_body)

def load_transcripts_os(
    transcripts: List[Dict[str, Any]],
    index_name: str
) -> None:
        helpers.bulk(OS_CLIENT, transcripts, index=index_name, raise_on_error=True, refresh=True)

# Usage:
# transcripts = asyncio.run(get_transcripts_embeddings_async(n_transcripts, bucket))