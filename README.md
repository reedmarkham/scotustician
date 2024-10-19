# scotustician

## Deployment (local):
Install [Docker](https://docs.docker.com/desktop/install/mac-install/).

Update `.env` to specify some resources: S3 bucket + file name for case summaries.

```
git clone https://github.com/reedmarkham/scotustician.git
cd scotustician
docker compose up -d
```

Check out the Swagger UI for the API: http://0.0.0.0:8000/docs

## Example usage:

Recommended: install [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/) and activate a `conda` environment:
```
conda create --name scotustician
conda activate scotustician
```

Now, run `test.py` to interact with the locally-deployed API, and load some data to S3:
```
pip3 install requests boto3
python3 test.py
```

## Reference:
A popular implementation of [Oyez.org](https://www.oyez.org/) API:
`https://github.com/walkerdb/supreme_court_transcripts`