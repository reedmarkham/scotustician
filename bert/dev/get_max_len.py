import json

import boto3
from transformers import BertTokenizer

BUCKET = 'scotustician-oral-argument'

def count_oa(bucket: str):
    # get the bucket
    bucket = boto3.resource('s3').Bucket(bucket)

    # use loop and count increment
    count_obj = 0
    for i in bucket.objects.all():
        count_obj = count_obj + 1
    return count_obj

# Load the BERT tokenizer.
tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', do_lower_case=True)

def get_max_len(sentences: list[str]):
    max_len = 0
    # For every sentence...
    for sent in sentences:
        # Tokenize the text and add `[CLS]` and `[SEP]` tokens.
        input_ids = tokenizer.encode(sent, add_special_tokens=True)

        # Update the maximum sentence length.
        max_len = max(max_len, len(input_ids))
        return max_len

# How many OAs in bucket
print(f'{count_oa(BUCKET)} OAs found in bucket: {BUCKET}')

# Initialize S3
s3 = boto3.client('s3')

# Build a transcript from the S3 bucket contents
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=BUCKET, PaginationConfig={'MaxItems': 1}):
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
                
                text_blocks = t['text_blocks']
                for tb in text_blocks:
                    text = tb['text']
                    transcript.append(f'{speaker}: {text}')

print(get_max_len(transcript))

                    