import os, json, datetime
from helpers import write_json_to_path

case_summary_path = os.getenv('CASE_SUMMARY_PATH')
case_full_path = os.getenv('CASE_FULL_PATH')

def get_case_fulls(case_summary_path):
	
	with open(case_summary_path, 'r') as case_summary:
		case_summaries_json = json.load(case_summary)
		
		for case_summary in case_summaries_json:
			case_summary_id = case_summary['ID']
			case_full_file = f'{case_full_path}/case_full_{case_summary_id}.json'
			write_json_to_path(case_summary['href'], case_full_file)
		
		case_summary.close()

	print("All case full JSONs written. ", datetime.now())

def main():
      get_case_fulls(case_summary_path)
 
if __name__ == '__main__':
    main()