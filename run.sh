#!/bin/zsh

export CASE_SUMMARY_URL='https://api.oyez.org/cases?per_page=0'
export CASE_SUMMARY_PATH='data/case_summary.json'
export CASE_FULL_PATH='data/case'
export OA_PATH='data/oa'

python3 get_case_summary.py
python3 get_case_fulls.py
python3 get_oral_arguments.py

sh sync_s3.sh $0