import os, json, datetime
from helpers import write_json_to_path

case_full_path = os.getenv('CASE_FULL_PATH')
oa_path = os.getenv('OA_PATH')

def get_oas(oa_path, case_full_path):
	existing_case_fulls = os.listdir(case_full_path)
	if not existing_case_fulls:
		print("Error: no case full JSONs found.")
	
	for case_full in existing_case_fulls:
		case_full_file = open((str(case_full_path+case_full)),'r')
		case_full_json = json.load(case_full_file)
		if ('oral_argument_audio' in case_full_json and case_full_json['oral_argument_audio']):
			for oa in case_full_json['oral_argument_audio']:
				oa_id = oa['id']
				oa_file = f'{oa_path}/oa_{oa_id}.json'
				write_json_to_path(oa['href'], oa_file)
		case_full_file.close()

	print("All oral argument JSONs written. ", datetime.now())