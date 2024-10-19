import json

import requests, boto3

# Specify S3 buckets
CASE_FULL_BUCKET = 'scotustician-case-full'
OA_BUCKET = 'scotustician-oral-argument'

# Initialize S3 client
s3 = boto3.client('s3')
print('Intialized S3 ...')

# Print out case summary
print(requests.get('http://127.0.0.1:8000/get/case_summary').json())

# Load case summaries to S3
requests.post('http://127.0.0.1:8000/post/sync_case_summary')
print('Synced case summary to S3 ...')

# Load all case fulls to S3
case_summaries = requests.get('http://127.0.0.1:8000/get/case_summary').json()
print(case_summaries)
for case in case_summaries:
    print(case)
    key = f'case_full_{case.ID}.json'
    s3.put_object(
        Body = json.dumps(requests.get(case.href).json()),
        Bucket = CASE_FULL_BUCKET,
        Key = key
    )
    print(f'Loaded: s3://{CASE_FULL_BUCKET}/{key} ...')

# Specify terms of interest and iterate through cases
terms = [1965, 1972]
for term in terms:
    cases = requests.get(f'http://127.0.0.1:8000/get/cases_by_term/{term}')[0:1]
    print(cases)
    for case in cases[0:1]:
        case_full = requests.get(f'http://127.0.0.1:8000/case_full/?term={term}&case={case_id}')
        print(case_full)
        # Get oral argument data and load to S3
        if ('oral_argument_audio' in case_full and case_full['oral_argument_audio']):
            for oa in case['oral_argument_audio']:
                key = f'oa_{oa.id}.json'
                s3.put_object(
                    Body = json.dumps(requests.get(oa.href).json()),
                    Bucket = OA_BUCKET,
                    Key = key
                )
                print(f'Loaded: s3://{OA_BUCKET}/{key} ...')