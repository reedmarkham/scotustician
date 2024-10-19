# scotustician

## Deployment:
Install [Docker](https://docs.docker.com/desktop/install/mac-install/).

Deploy locally, for example:
```
git clone https://github.com/reedmarkham/scotustician.git
cd scotustician
docker-compose up -d
```

# Examples:
Now deployed at `http://127.0.0.1:8000`, interacting via FastAPI in `test.py`:
```
pip install requests
pip install boto3
python3 test.py
```

## Reference:
[Oyez.org](https://www.oyez.org/) API unofficial documentation:
`https://github.com/walkerdb/supreme_court_transcripts`