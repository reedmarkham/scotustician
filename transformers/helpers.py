import json

import boto3
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, helpers

CLUSTER_URL = ''

def get_client(cluster_url = CLUSTER_URL, username = 'admin', password = 'admin'):
    client = OpenSearch(
        hosts=[cluster_url],
        http_auth=(username, password),
        verify_certs=False
    )
    return client

OS_CLIENT = get_client()
MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def count_oa(bucket: str):

    bucket = boto3.resource('s3').Bucket(bucket)

    n = 0
    for _ in bucket.objects.all():
        n += 1
    return n

def get_transcripts_embeddings(n_transcripts: int, bucket: str):

    s3 = boto3.client('s3')

    paginator = s3.get_paginator("list_objects_v2")
    transcripts = []
    for page in paginator.paginate(Bucket=bucket, PaginationConfig={'MaxItems': n_transcripts}):
        for c in page["Contents"]:
            transcript = []
            transcript_dims = []
            o = s3.get_object(Bucket=bucket, Key=c['Key'])['Body'].read().decode('utf-8')
            j = json.loads(o)
            for s in j['transcript']['sections']:
                for t in s['turns']:
                    if t['speaker'] is None:
                        speaker = 'None'
                    else:
                        speaker = t['speaker']['name']
                        if t['speaker']['roles'] is None:
                            role = 'petitioner'
                        else:
                            role = 'justice'
                    text_blocks = t['text_blocks']
                    for tb in text_blocks:
                        text = tb['text']
                        start = tb['start']
                        stop = tb['stop']
                        utterance = {}
                        utterance['oa_id'] = j['id']
                        utterance['speaker'] = speaker
                        utterance['role'] = role
                        utterance['text'] = text
                        utterance['embedding'] = MODEL.encode(text, convert_to_tensor=True)[0]
                        utterance['embedding_dim'] = utterance['embedding'].shape[0]
                        utterance['start'] = start
                        utterance['stop'] = stop
                        transcript.append(utterance)
        transcripts.append(transcript)
    return transcripts

def create_os_index(embedding_dim: int, index_name: str):
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

def load_transcripts_os(transcripts:list[list[dict]], index_name: str):
    for transcript in transcripts:
        helpers.bulk(OS_CLIENT, transcript, index=index_name, raise_on_error=True, refresh=True)