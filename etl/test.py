import json, pprint

import requests, boto3

from main import request

# Specify S3 buckets
CASE_FULL_BUCKET = 'scotustician-case-full'
OA_BUCKET = 'scotustician-oral-argument'

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
for case in case_summaries:
    case_id = case['ID']
    print(f'Getting case {case_id}')
    key = f'case_full_{case_id}.json'
    case_href = case['href']
    case_json = request(case_href)
    s3.put_object(
        Body = json.dumps(case_json),
        Bucket = CASE_FULL_BUCKET,
        Key = key
    )

    print(f'Loaded: s3://{CASE_FULL_BUCKET}/{key} ...')

print(f'Loaded case full JSONs to s3://{CASE_FULL_BUCKET}')

# Specify terms of interest, and iterate through cases; later, load some oral arguments to S3
terms = list(range(1955, 2025))
for term in terms:
    print(f'Getting cases for {term}...')
    cases = request(f'{HOST}/cases_by_term/{term}')
    for case in cases:
        case_id = case['ID']
        docket_number = case['docket_number']
        case_full = request(f'{HOST}/case_full/{term}/{docket_number}')
        if ('oral_argument_audio' in case_full and case_full['oral_argument_audio']):
            for session, oa in enumerate(case_full['oral_argument_audio']):
                oa_id = oa['id']
                key = f'oa_{oa_id}.json'
                oa_href = oa['href']

                oa_json = request(oa_href)
                oa_json['term'] = term
                oa_json['case_id'] = case_id
                oa_json['docket_number'] = docket_number
                oa_json['session'] = session

                print('-'*20,'Sample of Supreme Court oral argument: ', '-'*20)
                sample = oa_json['transcript']['sections'][0]['turns'][0]
                pprint.pprint(sample, compact=True) 
                print('-'*len('-'*20,'Sample of Supreme Court oral argument: ', '-'*20))

                s3.put_object(
                    Body = json.dumps(oa_json),
                    Bucket = OA_BUCKET,
                    Key = key
                )

                print(f'Loaded: s3://{OA_BUCKET}/{key} ...')

print(f'Loaded oral argument JSONs to s3://{OA_BUCKET}')