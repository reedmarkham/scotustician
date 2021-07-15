import json
from datetime import datetime

import boto3
import psycopg2

rds_host = 'scotustician.ckxnl8fcnva5.us-east-2.rds.amazonaws.com'
rds_db = 'postgres'
rds_port = '5432'

queries = ['oa_to_case.sql','speakers.sql','oa_transcript.sql','oa_transcript_labeled.sql','word_count_per_case.sql']

def main():
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

	for query in queries:
		print('Running query: ', query, datetime.now())
		path = 'query/%s' % (query)
		sql_file = open(path, 'r')
		cur.execute(sql_file.read())
		print('Query finished: ', query, datetime.now())

	print('Closing RDS connection: ', datetime.now())

	conn.close()

	print('RDS connection closed: ', datetime.now())

if __name__ == "__main__":
    main()