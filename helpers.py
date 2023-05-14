import json, os, datetime
from datetime import datetime
from ratelimit import limits, sleep_and_retry
import requests

@sleep_and_retry
@limits(calls=1, period=1)
def get_json(url):
    r = requests.get(url)
    r_json = r.json()
    if r.status_code != 200:
        raise Exception('API response: {}'.format(r.status_code))
    return r_json

def write_json_to_path(url, path):

    print(f"Requesting URL from {url}", datetime.now())

    j = get_json(url)

    with open(path, 'w') as dest:
        json.dump(j, dest)
        dest.close()
        print(f"{path} written", datetime.now())    

def path_to_list(path, output_list):
	for file in os.listdir(path):
		output_list.append(file)

def check_existing_files(path):
	output_list = []
	path_to_list(path, output_list)
	print(len(output_list), f" files found in {path} ", datetime.now())
	return output_list 