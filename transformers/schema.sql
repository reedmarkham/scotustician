-- Scotustician Database Schema
-- This file contains all DDL statements for creating the necessary tables

-- Create transcript embeddings table
CREATE TABLE IF NOT EXISTS scotustician.transcript_embeddings (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    vector vector(4096),
    case_name VARCHAR(255),
    term VARCHAR(10),
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255),
    source_key VARCHAR(500),
    xml_uri VARCHAR(500),
    speaker_list JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create utterance embeddings table with chunking metadata
CREATE TABLE IF NOT EXISTS scotustician.utterance_embeddings (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255) NOT NULL,
    utterance_index INTEGER NOT NULL,
    speaker_id VARCHAR(100),
    speaker_name VARCHAR(255),
    text TEXT NOT NULL,
    vector vector(4096) NOT NULL,
    word_count INTEGER,
    source_key VARCHAR(500),
    start_time_ms INTEGER,
    end_time_ms INTEGER,
    char_start_offset INTEGER,
    char_end_offset INTEGER,
    token_count INTEGER,
    embedding_model VARCHAR(100),
    embedding_dimension INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, utterance_index)
);

-- Create indexes for utterance embeddings
CREATE INDEX IF NOT EXISTS idx_utterance_case_id 
ON scotustician.utterance_embeddings(case_id);

CREATE INDEX IF NOT EXISTS idx_utterance_speaker 
ON scotustician.utterance_embeddings(speaker_name);

-- Indexes for efficient range queries during chunking
CREATE INDEX IF NOT EXISTS idx_utterance_time_range 
ON scotustician.utterance_embeddings(case_id, start_time_ms, end_time_ms);

CREATE INDEX IF NOT EXISTS idx_utterance_char_range 
ON scotustician.utterance_embeddings(case_id, char_start_offset, char_end_offset);

-- Index for efficient aggregation when generating case embeddings
CREATE INDEX IF NOT EXISTS idx_utterance_embedding_model 
ON scotustician.utterance_embeddings(case_id, embedding_model);

-- Create raw transcripts table
CREATE TABLE IF NOT EXISTS scotustician.raw_transcripts (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    raw_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create case decisions table
CREATE TABLE IF NOT EXISTS scotustician.case_decisions (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    case_name VARCHAR(255),
    term VARCHAR(10),
    docket VARCHAR(50),
    decision_date DATE,
    decision_type VARCHAR(50),
    disposition VARCHAR(100),
    majority_opinion_author VARCHAR(100),
    chief_justice VARCHAR(100),
    vote_split VARCHAR(20),
    procedural_ruling BOOLEAN,
    consolidated_cases TEXT[],
    lower_court VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create justice votes table
CREATE TABLE IF NOT EXISTS scotustician.justice_votes (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    justice_name VARCHAR(100) NOT NULL,
    vote_type VARCHAR(50) NOT NULL,
    opinion_type VARCHAR(50),
    is_author BOOLEAN,
    joined_opinions TEXT[]
);

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