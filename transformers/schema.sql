-- Scotustician Database Schema
-- This file contains all DDL statements for creating the necessary tables

-- Create transcript embeddings table
CREATE TABLE IF NOT EXISTS scotustician.transcript_embeddings (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    vector vector(384),
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

-- Create utterance embeddings table
CREATE TABLE IF NOT EXISTS scotustician.utterance_embeddings (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL,
    oa_id VARCHAR(255) NOT NULL,
    utterance_index INTEGER NOT NULL,
    speaker_id VARCHAR(100),
    speaker_name VARCHAR(255),
    text TEXT NOT NULL,
    vector vector(384) NOT NULL,
    word_count INTEGER,
    source_key VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, utterance_index)
);

-- Create indexes for utterance embeddings
CREATE INDEX IF NOT EXISTS idx_utterance_case_id 
ON scotustician.utterance_embeddings(case_id);

CREATE INDEX IF NOT EXISTS idx_utterance_speaker 
ON scotustician.utterance_embeddings(speaker_name);

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