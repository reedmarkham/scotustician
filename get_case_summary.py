import os
from helpers import write_json_to_path

case_summary_url = os.getenv('CASE_SUMMARY_URL')
case_summary_path = os.getenv('CASE_SUMMARY_PATH')

def main():
      write_json_to_path(case_summary_url, case_summary_path)
 
if __name__ == '__main__':
    main()