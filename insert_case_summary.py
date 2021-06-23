import os
import json
import re
import psycopg2
import boto3

s3r = boto3.resource('s3')
bucket = 'scotustician'
cs_key = 'data/case_summary.json'

conn = psycopg2.connect(
host = os.environ['SCOTUSTICIAN_RDS_HOST'], 
port = os.environ['SCOTUSTICIAN_RDS_PORT'], 
dbname = os.environ['SCOTUSTICIAN_RDS_DBNAME'], 
user = os.environ['SCOTUSTICIAN_RDS_USERNAME'], 
password = os.environ['SCOTUSTICIAN_RDS_PASSWORD'])
conn.autocommit = True
cur = conn.cursor()

def cases_rds_upload():
	sb = s3r.Bucket(bucket)
	obj = s3r.Object(bucket, cs_key)
	file_content = obj.get()['Body'].read().decode('utf-8')
	file_json = json.loads(file_content)
	cases = json.load(file_json)
	for case in cases:
		query = 'insert into public.case (case_id, term, docket_number, name, description, question) values (%s, %s, %s, %s, %s, %s);'
		data = (case['ID'], case['term'], case['docket_number'], case['name'], case['description'], case['question'])
		try:
			cur.execute(query, data)
		except Exception as exc:
			traceback.print_exc()
	return

conn.close()