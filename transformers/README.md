# Generating oral argument transcript embeddings using Hugging Face Sentence Transformeres

# Pre-requisites:
[Deploy an OpenSearch vector database](https://github.com/reedmarkham/scotustician-db)

# To-do:
* ~~Read oral argument JSONs from S3 (i.e. `s3://scotustician-oral-argument`)~~
* ~~Generate pre-trained model embeddings for each "utterance," mapped to each speaker (justice or petitioner), start/stop timestamps, and oral argument~~
* ~~Map each oral argument to case, term~~
* Store vectors (i.e. [OpenSearch](https://github.com/ev2900/OpenSearch_Neural_Search)); [tutorial](https://medium.com/marvelous-mlops/creating-vector-database-with-opensearch-7562b7451978)
* Explore similarity and/or sentiment analyses

# Ongoing development:
Recommended: install [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/) and activate a `conda` environment:
```
conda create --name scotustician-transformers
conda activate scotustician-transformers
```

Compute embeddings from JSONs on S3 and load to OpenSearch:
```
pip3 install boto3==1.34.29 sentence_transformers==2.2.2 numpy==1.26.4 opensearch-py==2.4.2
python3 load-embeddings.py
```
