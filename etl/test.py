import os, json, pprint

import requests, boto3

# Specify S3 buckets
CASE_FULL_BUCKET = os.environ('S3_CASE_FULL')
OA_BUCKET = os.environ('S3_OA')

# Initialize S3 client
s3 = boto3.client('s3')

print('Intialized S3 ...')

# Define API host
HOST = 'http://127.0.0.1:8000'

# Load case summaries to S3
requests.post(f'{HOST}/sync_case_summary')

print('Synced case summary to S3 ...')

# Load case fulls to S3
case_summaries = requests.get(f'{HOST}/case_summary').json()
for case in case_summaries[0:1]:
    case_id = case['ID']
    key = f'case_full_{case_id}.json'
    case_href = case['href']
    s3.put_object(
        Body = json.dumps(requests.get(case_href).json()),
        Bucket = CASE_FULL_BUCKET,
        Key = key
    )

    print(f'Loaded: s3://{CASE_FULL_BUCKET}/{key} ...')

# Specify terms of interest, and iterate through cases; later, load some oral arguments to S3
terms = [2020, 2022]
for term in terms:
    cases = requests.get(f'{HOST}/cases_by_term/{term}').json()
    for case in cases[0:1]:
        docket_number = case['docket_number']
        case_full = requests.get(f'{HOST}/case_full/{term}/{docket_number}').json()
        if ('oral_argument_audio' in case_full and case_full['oral_argument_audio']):
            for oa in case_full['oral_argument_audio']:
                oa_id = oa['id']
                key = f'oa_{oa_id}.json'
                oa_href = oa['href']

                print('-'*20,'Sample of Supreme Court oral argument: ', '-'*20)
                sample = requests.get(oa_href).json()['transcript']['sections'][0]['turns'][0]
                pprint.pprint(sample, compact=True) 
                print('-'*len('-'*20,'Sample of Supreme Court oral argument: ', '-'*20))

                s3.put_object(
                    Body = json.dumps(requests.get(oa_href).json()),
                    Bucket = OA_BUCKET,
                    Key = key
                )

                print(f'Loaded: s3://{OA_BUCKET}/{key} ...')