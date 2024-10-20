import json, pprint

import boto3
from sentence_transformers import SentenceTransformer, util

BUCKET = 'scotustician-oral-argument'
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def count_oa(bucket: str):
    # get the bucket
    bucket = boto3.resource('s3').Bucket(bucket)

    # use loop and count increment
    count_obj = 0
    for i in bucket.objects.all():
        count_obj = count_obj + 1
    return count_obj

# How many OAs in bucket
print(f'{count_oa(BUCKET)} OAs found in bucket: {BUCKET}')

# Initialize S3
s3 = boto3.client('s3')

# Build transcripts from S3 bucket contents
n_transcripts = 1
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=BUCKET, PaginationConfig={'MaxItems': n_transcripts}):
    for c in page["Contents"]:
        transcript = []
        o = s3.get_object(Bucket=BUCKET, Key=c['Key'])['Body'].read().decode('utf-8')
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
                    utterance['embedding'] = model.encode(text, convert_to_tensor=True)
                    utterance['start'] = start
                    utterance['stop'] = stop
                    transcript.append(utterance)

# Show what the transcript looks like
pprint.pprint(transcript)