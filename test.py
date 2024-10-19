import json

import requests, boto3

# Specify S3 buckets
CASE_FULL_BUCKET = 'scotustician-case-full'
OA_BUCKET = 'scotustician-oral-argument'

# Initialize S3 client
s3 = boto3.client('s3')

# Load case summaries to S3
requests.post('http://127.0.0.1:8000/post/sync_case_summary')

# Load all case fulls to S3
case_summaries = requests.get('http://127.0.0.1:8000/get/case_summary')
for case in case_summaries[0:1]:
    key = f'case_full_{case.ID}.json'
    s3.put_object(
        Body = json.dumps(requests.get(case.href)),
        Bucket = CASE_FULL_BUCKET,
        Key = key
    )

# Specify terms of interest and load oral arguments to S3
terms = [1965, 1972]
for term in terms:
    cases = requests.get('http://127.0.0.1:8000/get/cases_by_term/{term}')
    for case in cases:
        case_full = requests.get('http://127.0.0.1:8000/case_full/?term={term}&case={case_id}')
        if ('oral_argument_audio' in case_full and case_full['oral_argument_audio']):
            for oa in case['oral_argument_audio']:
                key = f'oa_{oa.id}.json'
                s3.put_object(
                    Body = json.dumps(requests.get(oa.href)),
                    Bucket = OA_BUCKET,
                    Key = key
                )