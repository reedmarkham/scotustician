# Generating oral argument transcript embeddings using Hugging Face Sentence Transformeres

# To-do:
* ~~Read oral argument JSONs from S3 (i.e. `s3://scotustician-oral-argument`)~~
* ~~Generate pre-trained model embeddings for each "utterance," mapped to each speaker (justice or petitioner), start/stop timestamps, and oral argument~~
* Map each oral argument to case, term
* Store vectors (i.e. [OpenSearch](https://github.com/ev2900/OpenSearch_Neural_Search)); [tutorial](https://medium.com/marvelous-mlops/creating-vector-database-with-opensearch-7562b7451978)
* Explore similarity and/or sentiment analyses

# Ongoing development:
Recommended: install [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/) and activate a `conda` environment:
```
conda create --name scotustician-transformers
conda activate scotustician-transformers
```

Check out transcript(s) and corresponding embeddings:
```
cd dev
pip3 install boto3 sentence_transformers numpy==1.26.4
python3 embeddings.py
```
