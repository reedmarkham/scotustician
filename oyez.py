import os
import json
from datetime import datetime

import requests
import ratelimit
from ratelimit import limits, sleep_and_retry

url = 'https://api.oyez.org/cases?per_page=0'

@sleep_and_retry
@limits(calls=1, period=1)
def get_json(url):
    r = requests.get(url)
    r_json = r.json()
    if r.status_code != 200:
        raise Exception('API response: {}'.format(r.status_code))
    return r_json

def check_existing_files():
	existing_case_summaries = []
	for file in os.listdir('data/case/summary'):
		existing_case_summaries.append(file)
	existing_case_fulls = []
	for file in os.listdir('data/case/full'):
		existing_case_fulls.append(file)
	existing_oas = []
	for file in os.listdir('data/oa'):
		existing_oas.append(file)
	print(len(existing_case_summaries)," case summary JSONs found.", datetime.now())
	print(len(existing_case_fulls)," case full JSONs found.", datetime.now())
	print(len(existing_oas)," oral argument JSONs found.", datetime.now())
	return existing_case_summaries, existing_case_fulls, existing_oas

def get_case_summaries(url, existing_case_summaries):
	case_summary = get_json(url)
	with open('data/case_summary.json', 'w') as dest:
		json.dump(case_summary, dest)
		dest.close()
		print("Case summary JSON written.", datetime.now())
	with open('data/case_summary.json', 'r') as case_summaries:
		case_summaries_json = json.load(case_summaries)
		for case in case_summaries_json:
			case_summary_file = 'data/case/summary/case_summary_{}.json'.format(case['ID'])
			if not (case_summary_file.split('/')[3] in existing_case_summaries):
				with open(case_summary_file, 'w') as dest:
					json.dump(case, dest)
					dest.close()
					print(case_summary_file, "written.", datetime.now())
		case_summaries.close()
	print("All case summary JSONs written.", datetime.now())
	return

def get_case_fulls(existing_case_fulls):
	with open('data/case_summary.json', 'r') as case_summaries:
		case_summaries_json = json.load(case_summaries)
		for case_summary in case_summaries_json:
			case_full_file = 'data/case/full/case_full_{}.json'.format(case_summary['ID'])
			if not (case_full_file.split('/')[3] in existing_case_fulls):
				with open(case_full_file, 'w') as dest:
					case_full = get_json(case_summary['href'])
					json.dump(case_full, dest)
					dest.close()
					print(case_full_file, "written.", datetime.now())
		case_summaries.close()
	print("All case full JSONs written.", datetime.now())
	return

def get_oas(existing_case_fulls, existing_oas):
	if not existing_case_fulls:
		existing_case_fulls = os.listdir('data/case/full')
		if not existing_case_fulls:
			print("Error: no case full JSONs found.")
	for case_full in existing_case_fulls:
		case_full_file = open((str('data/case/full/'+case_full)),'r')
		case_full_json = json.load(case_full_file)
		if ('oral_argument_audio' in case_full_json and case_full_json['oral_argument_audio']):
			for oa in case_full_json['oral_argument_audio']:
				oa_file = 'data/oa/oa_{}.json'.format(oa['id'])
				if not (oa_file.split('/')[2] in existing_oas):
					with open(oa_file, 'w') as dest:
						oa_json = get_json(oa['href'])
						json.dump(oa_json, dest)
						dest.close()
						print(oa_file, "written.", datetime.now())
		case_full_file.close()
	print("All oral argument JSONs written.", datetime.now())
	return

def main():
	print("Checking existing data.", datetime.now())
	existing_case_summaries, existing_case_fulls, existing_oas = check_existing_files()
	get_case_summaries(url, existing_case_summaries)
	get_case_fulls(existing_case_fulls)
	get_oas(existing_case_fulls, existing_oas)
	print("All data written.", datetime.now())

if __name__ == "__main__":
    main()