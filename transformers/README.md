# 🗣️ scotustician

Generating oral argument transcript embeddings using Hugging Face Sentence Transformers

# Pre-requisites:
[Deploy an OpenSearch vector database](https://github.com/reedmarkham/scotustician-db)

# Local development:
Recommended: install [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/) and activate a `conda` environment:
```
conda create --name scotustician-transformers
conda activate scotustician-transformers
```

Compute embeddings from JSONs on S3 and load to OpenSearch:
```
pip3 install boto3==1.34.29 sentence_transformers==2.2.2 numpy==1.26.4 opensearch-py==2.4.2
python3 main.py
```
