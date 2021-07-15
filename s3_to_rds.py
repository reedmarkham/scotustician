import os
import re
import json
from json.decoder import JSONDecodeError
import traceback
from datetime import datetime

import boto3
import psycopg2

bucket = 'scotustician'
s3_client = boto3.client('s3')
s3_resource = boto3.resource('s3')

rds_host = 'scotustician.ckxnl8fcnva5.us-east-2.rds.amazonaws.com'
rds_db = 'postgres'
rds_port = '5432'

tables = ['raw.case_summary','raw.case_full','raw.oa']

def get_s3_files(bucket):
	print("Checking S3 for files: ", datetime.now())
	s3_files = []
	paginator = s3_client.get_paginator('list_objects_v2')
	pages = paginator.paginate(Bucket=bucket)
	for page in pages:
		for obj in page['Contents']:
			s3_files.append(obj['Key'])
	print(len(s3_files), " files in S3 found: ", datetime.now())
	return s3_files

def get_rds_files(cur, table_name):
	print("Checking RDS table: ", table_name, datetime.now())
	query = 'select distinct s3_key from %s;' % (table_name)
	cur.execute(query)
	fetched = cur.fetchall()
	rds_files = list(sum(fetched, ()))
	print(len(rds_files), " files found in RDS table: ", table_name, datetime.now())
	return rds_files

def determine_rds_upload(s3_files, rds_files):
	s3_to_rds = [file for file in s3_files if not any(rds in file for rds in rds_files)]
	return s3_to_rds

def upload_rds(bucket, s3_to_rds, cur, table_name):
	print("Beginning upload to ", table_name, datetime.now())
	for key in s3_to_rds:
		if table_name.split('.')[1] in key:
			print("Uploading ", key, " to ", table_name, datetime.now())
			obj = s3_client.get_object(Bucket=bucket, Key=key)
			content = obj['Body'].read()
			try:
				j = json.loads(content)
				query = 'insert into {} (s3_key, last_updated, raw_file) values (%s, %s, %s) on conflict (s3_key) do update set last_updated=excluded.last_updated, raw_file=excluded.raw_file;'.format(table_name) 
				data = (key, datetime.now(), json.dumps(j))
				try:
					cur.execute(query, data)
					print("Successfully uploaded ", key, " to ", table_name, datetime.now())
				except Exception as exc:
					traceback.print_exc()
					pass
			except JSONDecodeError:
				print("Error with JSON file: ", key, datetime.now())
				pass
	print("Finished upload to ", table_name, datetime.now())
	return

def main():
	s3_files = get_s3_files(bucket)

	print('Loading RDS credentials: ', datetime.now())

	session = boto3.session.Session()
	client = session.client(service_name='secretsmanager',region_name='us-east-2')
	secret = client.get_secret_value(SecretId='scotustician_rds')
	secret_dict = json.loads(secret['SecretString'])
	username = secret_dict['username']
	password = secret_dict['password']

	print('Connecting to RDS: ', datetime.now())

	conn = psycopg2.connect(host=rds_host,port=rds_port,database=rds_db, user=username, password=password)
	conn.autocommit = True
	cur = conn.cursor()

	for table in tables:
		rds_files = get_rds_files(cur, table)
		rds_list = determine_rds_upload(s3_files, rds_files)
		upload_rds(bucket, rds_list, cur, table)

	print('Closing RDS connection: ', datetime.now())

	conn.close()

	print('RDS connection closed: ', datetime.now())

if __name__ == "__main__":
    main()