# scotustician
## Data science with Supreme Court oral argument transcripts:
***
* [etl](./etl): gather JSON files to represent cases and oral arguments, using FastAPI, Docker, and S3
* [transformers](./transformers): produce and explore transcript embeddings, using Hugging Face Transformers; load vectors to OpenSearch, deployed [like so](https://github.com/reedmarkham/scotustician-db)