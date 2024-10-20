import json, os

from fastapi import FastAPI
from ratelimit import limits, sleep_and_retry
import requests, httpx, boto3

# Oyez API URLs:
OYEZ_CASE_SUMMARY = os.environ['OYEZ_CASE_SUMMARY']
OYEZ_CASES_TERM_PREFIX = os.environ['OYEZ_CASES_TERM_PREFIX']
def oyez_api_case(term: int, docket_number: str):
    return f'https://api.oyez.org/cases/{term}/{docket_number}'

# S3 URIs:
S3_CASE_SUMMARY = os.environ['S3_CASE_SUMMARY']

# File names within S3 buckets:
CASE_SUMMARY_KEY = os.environ['CASE_SUMMARY_KEY']

app = FastAPI(
    title = 'scotustician',
    description='''
    A FastAPI tool to interact with the Oyez.org API for Supreme Court case data
    ''',
    version = '0.1.0'
    )

@sleep_and_retry
@limits(calls=1, period=1)
def request(url: str):
    try:
        return requests.get(url).json()
    except:
        print(f'API response: {requests.get(url).status_code}')

@app.get("/case_summary")
async def case_summary():
    async with httpx.AsyncClient() as client:
        response = await client.get(OYEZ_CASE_SUMMARY)
        case_summary = response.json()
        return case_summary

@app.post("/sync_case_summary")
def sync_case_summary():
    s3 = boto3.client('s3')
    s3.put_object(
        Body=json.dumps(request(OYEZ_CASE_SUMMARY)),
        Bucket=S3_CASE_SUMMARY,
        Key=CASE_SUMMARY_KEY
    )

@app.get("/cases_by_term/{term}")
async def cases_by_term(term: int):
    async with httpx.AsyncClient() as client:
        response = await client.get(OYEZ_CASES_TERM_PREFIX+str(term))
        cases = response.json()
        return cases

@app.get("/case_full/{term}/{docket_number}")
async def case_full(term: int, docket_number: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(oyez_api_case(term, docket_number))
        case_full = response.json()
        return case_full