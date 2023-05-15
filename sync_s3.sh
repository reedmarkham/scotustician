#!/bin/zsh

export BUCKET='s3://scotustician'
export CASE_SUMMARY_PATH='data/case_summary.json'
export CASE_FULL_PATH='data/case'
export OA_PATH='data/oa'

aws s3 sync ./$CASE_SUMMARY_PATH $BUCKET
aws s3 sync ./$CASE_FULL_PATH $BUCKET
aws s3 sync ./$OA_PATH $BUCKET