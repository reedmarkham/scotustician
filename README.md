# scotustician

## Deployment:
Install [Docker](https://docs.docker.com/desktop/install/mac-install/) and [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/).

Update `.env` to specify some resources: S3 bucket + file name for case summaries.

Deploy locally, for example:
```
git clone https://github.com/reedmarkham/scotustician.git
cd scotustician
docker-compose up -d
```

## Examples:
Now deployed at `http://127.0.0.1:8000`, interacting via FastAPI in `test.py`:
```
conda create --name scotustician
conda activate scotustician

pip3 install requests
pip3 install boto3
python3 test.py
```

## Reference:
A popular implementation of [Oyez.org](https://www.oyez.org/) API:
`https://github.com/walkerdb/supreme_court_transcripts`