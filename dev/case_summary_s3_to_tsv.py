import json

import pandas as pd, boto3

S3_CASE_SUMMARY = 'scotustician-case-summary'
CASE_SUMMARY_KEY = 'case_summary.json'
CASE_SUMMARY_TSV = './case_summary.tsv'

# Initialize S3
s3 = boto3.resource('s3')

# Gather the case_summary.json from S3 to a DF
case_summary = s3.Object(S3_CASE_SUMMARY, CASE_SUMMARY_KEY)
case_summary_df = pd.DataFrame.from_records(
    json.loads(case_summary.get()['Body'].read().decode('utf-8'))
    )

print(case_summary_df.head())
print(f'{len(case_summary_df)} cases loading to TSV')

# Write DF to TSV
case_summary_df.to_csv(CASE_SUMMARY_TSV, sep='\t', index=False)