#!/bin/zsh

python3 oyez.py

aws s3 sync ./data/case/summary s3://scotustician
aws s3 sync ./data/case/full s3://scotustician
aws s3 sync ./data/oa s3://scotustician

python3 s3_to_rds.py

python3 rds.py