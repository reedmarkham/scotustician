import boto3
import ratelimit
from ratelimit import limits, sleep_and_retry
import requests

import re
import json
import traceback
import time
import datetime
from datetime import datetime

s3 = boto3.client('s3')
s3r = boto3.resource('s3')
bucket = 'scotustician'
cs_url = 'https://api.oyez.org/cases?per_page=0'
cs_key = 'data/case_summary.json'

def connect_to_rds():
	try:
		conn = psycopg2.connect(
		host = os.environ['SCOTUSTICIAN_RDS_HOST'], 
		port = os.environ['SCOTUSTICIAN_RDS_PORT'], 
		dbname = os.environ['SCOTUSTICIAN_RDS_DBNAME'], 
		user = os.environ['SCOTUSTICIAN_RDS_USERNAME'], 
		password = os.environ['SCOTUSTICIAN_RDS_PASSWORD'])
		conn.autocommit = True
		cur = conn.cursor()
	except Exception as exc:
		traceback.print_exc()
		print("Could not connect to RDS.")
	return

@sleep_and_retry
@limits(calls=1, period=1)
def call_api(url):
    print(url, datetime.now())
    r = requests.get(url)
    r_json = r.json()
    if r.status_code != 200:
        raise Exception('API response: {}'.format(r.status_code))
    return r_json

def get_case_summary_json():
	cs_json = call_api(cs_url)
	with open(cs_key, 'w') as dest:
		try:
			json.dump(cs_json, dest, indent=4, sort_keys=True)
		except Exception as exc:
			traceback.print_exc()
			print("Could not write case summary JSON file to disk.")
		try:
			s3.upload_file(cs_key, bucket, cs_key)
		except Exception as exc:
			traceback.print_exc()
			print("Could not upload case summary JSON file to S3.")
	return

def check_s3_for_cases():
	sb = s3r.Bucket(bucket)
	files_in_bucket = list(sb.objects.filter(Prefix='data/'))
	files_in_bucket = [re.sub('data/','',f.key) for f in files_in_bucket]
	s3_cases = []
	for f in files_in_bucket:
		term = f.split('.')[0]
		docket_number = f.split('.')[1]
		s3_case = (term, docket_number)
		s3_cases.append(s3_case)
		print("Already in S3: ", s3_case)
	return s3_cases

def case_summary_json_to_cases():
	with open(cs_key) as cs_json_file:
		loaded_cs_json_file = json.load(cs_json_file)
	cases = {(case["term"], case["docket_number"]): case for case in loaded_cs_json_file}
	return cases

def parse_case_transcripts(term, docket):
	url = f"https://api.oyez.org/cases/{term}/{docket}"
	case = call_api(url)
	if not ("oral_argument_audio" in case and case["oral_argument_audio"]):
		return case, []
	else:
		oa_sessions = case["oral_argument_audio"]
		transcripts = []
		for session in oa_sessions:
			transcript = call_api(session["href"])
			transcripts.append(transcript)
		return case, transcripts

def write_oa_json(term, docket, case, transcripts):
	case_path = f"data/{term}.{docket}.json"
	with open(case_path, "w") as case_file:
		json.dump(case, case_file, indent=4, sort_keys=True)
	oa_id = 0
	for transcript in transcripts:
		oa_id += 1
		transcript_file = "data/{}.{}.oa{}.json".format(term, docket, oa_id)
		with open(transcript_file, "w") as transcript_dest:
			try:
				json.dump(transcript, transcript_dest, indent=4, sort_keys = True)
			except Exception as exc:
				traceback.print_exc()
				print("Could not write OA JSON file to disk.")
			try:
				s3.upload_file(transcript_file, bucket, transcript_file)
			except Exception as exc:
				traceback.print_exc()
				print("Could not write OA JSON file to disk.")
	return

def get_oa_jsons(cases, s3_cases):
	for term, docket in cases.keys():
		if (term, docket) not in s3_cases:
			try:
				case, transcripts = parse_case_transcripts(term, docket)
				if not transcripts:
					continue
				write_oa_json(term, docket, case, transcripts)
				print("File written:", term + " " + docket, datetime.now())
			except Exception as exc:
				traceback.print_exc()
				print("Failed:", term + " " + docket, datetime.now())
	return

def cases_from_s3_to_rds():
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

def oa_from_s3_to_rds():
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

def main():
	connect_to_rds()
	get_case_summary_json()
	#s3_cases = check_s3_for_cases()
	s3_cases = []
	cases = case_summary_json_to_cases()
	cases_from_s3_to_rds()
	get_oa_jsons(cases, s3_cases)
	oa_from_s3_to_rds()
	conn.close()

if __name__ == "__main__":
    main()