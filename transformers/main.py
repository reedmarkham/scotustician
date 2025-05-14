# Standard library imports
import pprint
import asyncio
import json

# Helper file imports
from helpers import format_size, count_oa, get_transcripts_embeddings_async, create_os_index, load_transcripts_os, generate_tsne_2d

BUCKET = 'scotustician-oral-argument'
N_TRANSCRIPTS = count_oa(BUCKET)
INDEX_NAME = 'oral-argument'

# How many OAs in bucket?
print(f'{count_oa(BUCKET)} OAs found in bucket: {BUCKET}')

# Build transcripts from S3 bucket contents (now async)
transcripts_nested = asyncio.run(get_transcripts_embeddings_async(N_TRANSCRIPTS, BUCKET))

# Flatten the list of lists (since each transcript is a list of utterances)
transcripts = [item for sublist in transcripts_nested for item in sublist]

# Print dataset size as JSON
json_size = len(json.dumps(transcripts).encode('utf-8'))
print(f"Dataset size (JSON): {format_size(json_size)}")

# Show a sample transcript
pprint.pprint(transcripts[0])

# For `transcripts` what is max embedding vector size?
embedding_dim = max(t['embedding_dim'] for t in transcripts)

# Create OS index
create_os_index(embedding_dim, INDEX_NAME)

# Load transcripts to OpenSearch
load_transcripts_os(transcripts, INDEX_NAME)

# After loading data to OpenSearch:
df_2d = generate_tsne_2d('oral-argument', n_samples=1000)
print(df_2d.head())