# Generating oral argument transcript embeddings using BERT

# To-do:
* Serialize text data from JSONs on S3 (i.e. `s3://scotustician-oral-argument`)
* [Generate BERT embeddings for each "utterance," mapped to each speaker (justice or petitioner)](https://mccormickml.com/2019/05/14/BERT-word-embeddings-tutorial/#sentence-vectors)
* Map each set of speakers and utterance BERT embeddings to each oral argument (as well as case)
* Store BERT embeddings vectors (i.e. [OpenSearch](https://github.com/ev2900/OpenSearch_Neural_Search))
* Explore some similarity (by oral argument/case) and/or sentiment analyses (by oral argument/speaker) from BERT embeddings vectors

# Ongoing development:
Recommended: install [Miniconda](https://docs.anaconda.com/miniconda/miniconda-install/) and activate a `conda` environment:
```
conda create --name scotustician-bert
conda activate scotustician-bert
```

Exploring maximum transcript lengths:
```
pip3 install boto3 transformers
python3 dev/get_max_len.py
```