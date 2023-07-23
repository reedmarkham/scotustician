#!/bin/zsh

export BUCKET=$0
export CASE_SUMMARY_PATH='data/case_summary.json'
export CASE_FULL_PATH='data/case'
export OA_PATH='data/oa'

aws s3api put-object --body ./$CASE_SUMMARY_PATH --key case_summary.json --bucket scotustician-case-summary
aws s3 sync ./$CASE_FULL_PATH $BUCKET
aws s3 sync ./$OA_PATH $BUCKET