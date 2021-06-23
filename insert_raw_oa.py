import os
import json
import re
import psycopg2
import boto3


s3r = boto3.resource('s3')
bucket = 'scotustician'

conn = psycopg2.connect(
host = os.environ['SCOTUSTICIAN_RDS_HOST'], 
port = os.environ['SCOTUSTICIAN_RDS_PORT'], 
dbname = os.environ['SCOTUSTICIAN_RDS_DBNAME'], 
user = os.environ['SCOTUSTICIAN_RDS_USERNAME'], 
password = os.environ['SCOTUSTICIAN_RDS_PASSWORD'])
conn.autocommit = True
cur = conn.cursor()

def oa_rds_upload():
	sb = s3r.Bucket(bucket)
	files_in_bucket = list(sb.objects.filter(Prefix='data/'))
	files_in_bucket = [re.sub('data/','',f.key) for f in files_in_bucket]
	for file in files_in_bucket:
		print(file)
		obj = s3r.Object(bucket, 'data/'+file)
		file_content = obj.get()['Body'].read().decode('utf-8')
		file_json = json.loads(file_content)
		oa_id = file_json['id']
		term = file.split('.')[0]
		docket_number = file.split('.')[1]
		query = 'insert into "raw.oa" ("oa_id","term","docket_number","raw_file") values (%s, %s, %s, %s);' 
		data = (oa_id, term, docket_number, json.dumps(file_json))
		try:
			cur.execute(query, data)
		except Exception as exc:
			traceback.print_exc()
	return

oa_rds_upload()

conn.close()