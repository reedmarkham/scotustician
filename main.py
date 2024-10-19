import json, os

from fastapi import FastAPI
from ratelimit import limits, sleep_and_retry
import requests, boto3

DESCRIPTION= '''
A FastAPI wrapper to interact with the Oyez.org API for Supreme Court case data
'''

# Oyez API URLs:
OYEZ_CASE_SUMMARY = 'https://api.oyez.org/cases?per_page=0'
OYEZ_CASES_TERM_PREFIX = 'https://api.oyez.org/cases?per_page=0&filter=term:'
def oyez_api_case(term: int, case_id: str):
    return f'https://api.oyez.org/cases/{term}/{case_id}'

# S3 URIs:
S3_CASE_SUMMARY = os.environ['S3_CASE_SUMMARY']

# File names within S3 buckets:
CASE_SUMMARY_KEY = os.environ['CASE_SUMMARY_KEY']

app = FastAPI(
    title = 'scotustician',
    description=DESCRIPTION,
    version = '0.1.0'
    )

@sleep_and_retry
@limits(calls=1, period=1)
def request(url):
    try:
        return requests.get(url).json()
    except:
        print(f'API response: {requests.get(url).status_code}')

@app.get("/case_summary/")
def case_summary():
    return request(OYEZ_CASE_SUMMARY)

@app.post("/sync_case_summary/")
def sync_case_summary():
    s3 = boto3.client('s3')
    s3.put_object(
        Body=json.dumps(case_summary()),
        Bucket=S3_CASE_SUMMARY,
        Key=CASE_SUMMARY_KEY
    )

@app.get("/cases_by_term/{term}")
def cases_by_term (term: int):
    return request(OYEZ_CASES_TERM_PREFIX+term)

@app.get("/case_full/")
def case_full (term: int, case_id: str):
    return request(oyez_api_case(term, case_id))