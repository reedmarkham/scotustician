import requests
import pandas as pd
from datetime import datetime
from ratelimit import limits, sleep_and_retry

print("Script began: ",datetime.now())

@sleep_and_retry
@limits(calls=10, period=10)
def call_api(url):
	print(f"Getting {url}")
	response = requests.get(url)
	parsed = response.json()
	return parsed

case_summaries_json = call_api('https://api.oyez.org/cases?per_page=0')

cases = []

for case_summary in case_summaries_json:
    df = pd.json_normalize(case_summary)
    cases.append(df)
    
cases_df = pd.concat(cases)
case_summary_df = cases_df[['ID','name','href','docket_number','term']].set_index('ID')
case_summary_df.to_csv('case_summary.csv', index=True)


case_summary_df = pd.read_csv('data/case_summary.csv')

print("Case table ready: ",datetime.now())

recent_cases = case_summary_df[case_summary_df['term'] >= "2000"]

oa_list = []

for index, case in recent_cases.iterrows():
    case_json = call_api(case['href'])
    case_id = case_json['ID']
    if case_json['oral_argument_audio'] is not None:
    	oa = pd.json_normalize(case_json['oral_argument_audio'])[['id','title','href']].set_index('id')
    	oa['case_id'] = case_id
    	oa = oa[['case_id','title','href']]
    	oa_list.append(oa)

oa_df = pd.concat(oa_list)
oa_df.to_csv('oa_summary.csv', index=True)

print("OA table ready: ",datetime.now())

oa_df = pd.read_csv('data/oa_summary.csv')