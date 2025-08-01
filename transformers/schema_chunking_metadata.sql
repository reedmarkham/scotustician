-- Add chunking metadata columns to utterance_embeddings table
ALTER TABLE scotustician.utterance_embeddings 
ADD COLUMN IF NOT EXISTS start_time_ms INTEGER,
ADD COLUMN IF NOT EXISTS end_time_ms INTEGER,
ADD COLUMN IF NOT EXISTS char_start_offset INTEGER,
ADD COLUMN IF NOT EXISTS char_end_offset INTEGER,
ADD COLUMN IF NOT EXISTS token_count INTEGER,
ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100),
ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;

-- Index for efficient range queries during chunking
CREATE INDEX IF NOT EXISTS idx_utterance_time_range 
ON scotustician.utterance_embeddings(case_id, start_time_ms, end_time_ms);

CREATE INDEX IF NOT EXISTS idx_utterance_char_range 
ON scotustician.utterance_embeddings(case_id, char_start_offset, char_end_offset);

-- Index for efficient aggregation when generating case embeddings
CREATE INDEX IF NOT EXISTS idx_utterance_embedding_model 
ON scotustician.utterance_embeddings(case_id, embedding_model);