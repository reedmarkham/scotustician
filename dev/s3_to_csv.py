import json

import pandas as pd, boto3

S3_CASE_SUMMARY = 'scotustician-case-summary'
CASE_SUMMARY_KEY = 'case_summary.json'
CASE_SUMMARY_CSV = './case_summary.csv'

s3 = boto3.resource('s3')

case_summary = s3.Object(S3_CASE_SUMMARY, CASE_SUMMARY_KEY)

case_summary_df = pd.DataFrame.from_records(
    json.loads(case_summary.get()['Body'].read().decode('utf-8'))
    )

case_summary_df.to_csv(CASE_SUMMARY_CSV)
