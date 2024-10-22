import pprint

from helpers import count_oa, get_transcripts_embeddings, create_os_index, load_transcripts_os

BUCKET = 'scotustician-oral-argument'
N_TRANSCRIPTS = 1
INDEX_NAME = 'oral-argument'

# How many OAs in bucket?
print(f'{count_oa(BUCKET)} OAs found in bucket: {BUCKET}')

# Build transcripts from S3 bucket contents
transcripts = get_transcripts_embeddings(N_TRANSCRIPTS, BUCKET)

# Show a sample transcript
pprint.pprint(transcripts[0])

# For `transcripts` what is max embedding vector size?
embedding_dim = max(transcripts, key=lambda x:x['embedding_dim'])

# Create OS index
create_os_index(embedding_dim, INDEX_NAME)

# Load transcripts to OpenSearch
load_transcripts_os(transcripts, INDEX_NAME)