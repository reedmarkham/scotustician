# Standard library imports
import os
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

# Third party library imports
import boto3
import aioboto3
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, helpers
from sklearn.manifold import TSNE
import numpy as np
import pandas as pd

CLUSTER_URL = os.getenv('CLUSTER_URL')
MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def format_size(num_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"

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

def generate_tsne_2d(
    index_name: str,
    n_samples: int = 1000,
    random_state: int = 42
    ) -> pd.DataFrame:
        """
        Fetches up to n_samples embeddings from OpenSearch and returns a DataFrame with 2D t-SNE projections.
        """
        # Query OpenSearch for embeddings
        query = {
            "size": n_samples,
            "_source": ["embedding", "oa_id", "speaker", "role", "text"]
        }
        results = OS_CLIENT.search(index=index_name, body=query)
        hits = results['hits']['hits']

        if not hits:
            raise ValueError("No data found in OpenSearch index.")

        embeddings = np.array([hit['_source']['embedding'] for hit in hits])
        meta = [{
            "oa_id": hit['_source'].get('oa_id'),
            "speaker": hit['_source'].get('speaker'),
            "role": hit['_source'].get('role'),
            "text": hit['_source'].get('text')
        } for hit in hits]

        # t-SNE projection
        tsne = TSNE(n_components=2, random_state=random_state)
        embeddings_2d = tsne.fit_transform(embeddings)

        # Combine with metadata
        df = pd.DataFrame(meta)
        df['tsne_x'] = embeddings_2d[:, 0]
        df['tsne_y'] = embeddings_2d[:, 1]
        return df

# Example usage:
# transcripts = asyncio.run(get_transcripts_embeddings_async(n_transcripts, bucket))