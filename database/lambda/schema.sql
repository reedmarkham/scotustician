-- Scotustician Database Schema
-- This file creates all necessary tables for the Scotustician application

-- Ensure we're using the correct schema
SET search_path TO scotustician, public;

-- Drop deprecated tables first (cleanup from old schema)
DROP TABLE IF EXISTS scotustician.utterance_embeddings CASCADE;
DROP TABLE IF EXISTS scotustician.transcript_chunks CASCADE;
DROP TABLE IF EXISTS scotustician.chunking_runs CASCADE;

CREATE TABLE IF NOT EXISTS scotustician.transcript_embeddings ( -- transcript embeddings table
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    vector vector(1024),
    case_name VARCHAR(255),
    term VARCHAR(10),
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255),
    source_key VARCHAR(500),
    xml_uri VARCHAR(500),
    speaker_list JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(id)
);

CREATE TABLE IF NOT EXISTS scotustician.oa_text ( -- raw OA text data
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255) NOT NULL,
    utterance_index INTEGER NOT NULL,
    speaker_id VARCHAR(50),
    speaker_name VARCHAR(255) NOT NULL,
    text TEXT NOT NULL,
    word_count INTEGER,
    token_count INTEGER,
    start_time_ms INTEGER,
    end_time_ms INTEGER,
    char_start_offset INTEGER,
    char_end_offset INTEGER,
    source_key VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, utterance_index)
);

CREATE TABLE IF NOT EXISTS scotustician.document_chunk_embeddings ( -- document chunk embeddings
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255) NOT NULL,
    section_id INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    vector vector(1024) NOT NULL,
    word_count INTEGER,
    token_count INTEGER,
    start_utterance_index INTEGER,
    end_utterance_index INTEGER,
    embedding_model VARCHAR(100),
    embedding_dimension INTEGER,
    source_key VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, oa_id, section_id)
);

CREATE TABLE IF NOT EXISTS scotustician.raw_transcripts ( -- raw transcripts for storing original data
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL UNIQUE,
    oa_id VARCHAR(255),
    case_name VARCHAR(500),
    term VARCHAR(10),
    docket_number VARCHAR(50),
    argument_date DATE,
    raw_text TEXT,
    raw_json JSONB,
    source_url VARCHAR(500),
    source_key VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scotustician.case_decisions ( -- case decisions
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL UNIQUE,
    case_name VARCHAR(500),
    term VARCHAR(10),
    docket_number VARCHAR(50),
    argument_date DATE,
    decision_date DATE,
    majority_author VARCHAR(100),
    decision_type VARCHAR(50),
    vote_count VARCHAR(20),
    raw_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scotustician.justice_votes ( -- justice votes
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    justice_name VARCHAR(100) NOT NULL,
    vote VARCHAR(50),
    opinion_type VARCHAR(50),
    raw_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, justice_name)
);

CREATE TABLE IF NOT EXISTS scotustician.processing_metadata ( -- processing metadata
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    processing_type VARCHAR(50) NOT NULL,
    status VARCHAR(50),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, processing_type)
);


-- Add vector columns if pgvector extension is available
-- This will be handled by the Lambda function conditionally

-- Create all indexes after tables are created
-- Indexes for transcript_embeddings
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_case_id ON scotustician.transcript_embeddings(case_id);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_oa_id ON scotustician.transcript_embeddings(oa_id);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_term ON scotustician.transcript_embeddings(term);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_created_at ON scotustician.transcript_embeddings(created_at);

-- Indexes for oa_text
CREATE INDEX IF NOT EXISTS idx_oa_text_case_id ON scotustician.oa_text(case_id);
CREATE INDEX IF NOT EXISTS idx_oa_text_oa_id ON scotustician.oa_text(oa_id);
CREATE INDEX IF NOT EXISTS idx_oa_text_speaker_name ON scotustician.oa_text(speaker_name);
CREATE INDEX IF NOT EXISTS idx_oa_text_created_at ON scotustician.oa_text(created_at);

-- Indexes for document_chunk_embeddings
CREATE INDEX IF NOT EXISTS idx_document_chunk_embeddings_case_id ON scotustician.document_chunk_embeddings(case_id);
CREATE INDEX IF NOT EXISTS idx_document_chunk_embeddings_oa_id ON scotustician.document_chunk_embeddings(oa_id);
CREATE INDEX IF NOT EXISTS idx_document_chunk_embeddings_created_at ON scotustician.document_chunk_embeddings(created_at);

-- Indexes for raw_transcripts
CREATE INDEX IF NOT EXISTS idx_raw_transcripts_case_id ON scotustician.raw_transcripts(case_id);
CREATE INDEX IF NOT EXISTS idx_raw_transcripts_term ON scotustician.raw_transcripts(term);
CREATE INDEX IF NOT EXISTS idx_raw_transcripts_argument_date ON scotustician.raw_transcripts(argument_date);

-- Indexes for case_decisions  
CREATE INDEX IF NOT EXISTS idx_case_decisions_case_id ON scotustician.case_decisions(case_id);
CREATE INDEX IF NOT EXISTS idx_case_decisions_term ON scotustician.case_decisions(term);
CREATE INDEX IF NOT EXISTS idx_case_decisions_decision_date ON scotustician.case_decisions(decision_date);

-- Indexes for justice_votes
CREATE INDEX IF NOT EXISTS idx_justice_votes_case_id ON scotustician.justice_votes(case_id);
CREATE INDEX IF NOT EXISTS idx_justice_votes_justice_name ON scotustician.justice_votes(justice_name);

-- Indexes for processing_metadata
CREATE INDEX IF NOT EXISTS idx_processing_metadata_case_id ON scotustician.processing_metadata(case_id);
CREATE INDEX IF NOT EXISTS idx_processing_metadata_status ON scotustician.processing_metadata(status);
CREATE INDEX IF NOT EXISTS idx_processing_metadata_processing_type ON scotustician.processing_metadata(processing_type);

-- Grant appropriate permissions (adjust as needed)
-- GRANT SELECT ON ALL TABLES IN SCHEMA scotustician TO readonly_user;
-- GRANT ALL ON ALL TABLES IN SCHEMA scotustician TO readwrite_user;