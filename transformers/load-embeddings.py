# Standard library imports
import pprint
import asyncio

# Helper file imports
from helpers import count_oa, get_transcripts_embeddings_async, create_os_index, load_transcripts_os

BUCKET = 'scotustician-oral-argument'
N_TRANSCRIPTS = 1
INDEX_NAME = 'oral-argument'

# How many OAs in bucket?
print(f'{count_oa(BUCKET)} OAs found in bucket: {BUCKET}')

# Build transcripts from S3 bucket contents (now async)
transcripts_nested = asyncio.run(get_transcripts_embeddings_async(N_TRANSCRIPTS, BUCKET))

# Flatten the list of lists (since each transcript is a list of utterances)
transcripts = [item for sublist in transcripts_nested for item in sublist]

# Show a sample transcript
pprint.pprint(transcripts[0])

# For `transcripts` what is max embedding vector size?
embedding_dim = max(t['embedding_dim'] for t in transcripts)

# Create OS index
create_os_index(embedding_dim, INDEX_NAME)

# Load transcripts to OpenSearch
load_transcripts_os(transcripts, INDEX_NAME)