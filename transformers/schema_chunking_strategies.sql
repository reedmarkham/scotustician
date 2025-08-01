-- Table to track different chunking strategies applied to transcripts
CREATE TABLE IF NOT EXISTS scotustician.transcript_chunks (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    chunk_index INTEGER NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params JSONB,
    start_utterance_index INTEGER NOT NULL,
    end_utterance_index INTEGER NOT NULL,
    utterance_count INTEGER NOT NULL,
    total_word_count INTEGER,
    total_token_count INTEGER,
    overlap_word_count INTEGER,
    overlap_token_count INTEGER,
    chunk_embedding vector(4096),
    chunk_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, strategy_name, chunk_index)
);

-- Index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_chunk_case_strategy 
ON scotustician.transcript_chunks(case_id, strategy_name);

CREATE INDEX IF NOT EXISTS idx_chunk_utterance_range 
ON scotustician.transcript_chunks(case_id, start_utterance_index, end_utterance_index);

-- Table to log chunking strategy executions
CREATE TABLE IF NOT EXISTS scotustician.chunking_runs (
    id SERIAL PRIMARY KEY,
    run_id UUID DEFAULT gen_random_uuid(),
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params JSONB,
    cases_processed INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    avg_chunk_size_words FLOAT,
    avg_chunk_size_tokens FLOAT,
    avg_overlap_percentage FLOAT,
    execution_time_ms INTEGER,
    status VARCHAR(50),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Example strategy_params JSON structures:
-- Fixed window: {"window_size": 512, "overlap": 128, "unit": "tokens"}
-- Semantic: {"similarity_threshold": 0.85, "min_size": 100, "max_size": 1000}
-- Speaker-based: {"group_by": "speaker", "max_utterances": 10}
-- Time-based: {"window_ms": 60000, "overlap_ms": 10000}