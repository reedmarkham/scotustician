import json, os, datetime
from datetime import datetime
from ratelimit import limits, sleep_and_retry
import requests

@sleep_and_retry
@limits(calls=1, period=1)
def get_json(url: str):
    r = requests.get(url)
    r_json = r.json()
    if r.status_code != 200:
        raise Exception(f'API response: {r.status_code}')
    return r_json

def write_json_to_path(url: str, path: str):
    print(f"Requesting URL from {url}", datetime.now())
    j = get_json(url)
    with open(path, 'w') as dest:
        json.dump(j, dest)
        dest.close()
        print(f"{path} written", datetime.now())
    return    

def path_to_list(path: str, output_list: list):
	for file in os.listdir(path):
		output_list.append(file)

def check_existing_files(path: str):
	output_list = []
	path_to_list(path, output_list)
	print(len(output_list), f" files found in {path} ", datetime.now())
	return output_list 