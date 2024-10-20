import json

import pandas as pd, boto3

s3 = boto3.resource('s3')

case_summary = s3.Object('scotustician-case-summary', 'case_summary.json')
case_summary_df = pd.DataFrame.from_records(
    json.loads(case_summary.get()['Body'].read().decode('utf-8'))
    )

oral_arguments = s3.Bucket('scotustician-oral-argument')
for o in oral_arguments.objects.all():
    print(o.get()['Body'].read().decode('utf-8'))
