-- Example queries for downstream case embedding generation using utterance embeddings

-- 1. Get all utterance embeddings for a case to generate case embedding
SELECT 
    utterance_index,
    speaker_name,
    text,
    vector,
    word_count,
    token_count,
    char_start_offset,
    char_end_offset
FROM scotustician.utterance_embeddings
WHERE case_id = '2023_smith-v-jones'
ORDER BY utterance_index;

-- 2. Fixed-size token window chunking (e.g., 512 tokens with 128 overlap)
WITH token_windows AS (
    SELECT 
        case_id,
        utterance_index,
        SUM(token_count) OVER (PARTITION BY case_id ORDER BY utterance_index) as cumulative_tokens,
        token_count,
        text,
        vector
    FROM scotustician.utterance_embeddings
    WHERE case_id = '2023_smith-v-jones'
),
chunks AS (
    SELECT 
        case_id,
        FLOOR((cumulative_tokens - token_count) / 384) as chunk_id,
        utterance_index,
        text,
        vector
    FROM token_windows
)
SELECT 
    chunk_id,
    array_agg(utterance_index ORDER BY utterance_index) as utterances,
    array_agg(text ORDER BY utterance_index) as texts,
    COUNT(*) as utterance_count
FROM chunks
GROUP BY case_id, chunk_id;

-- 3. Speaker-based chunking (group consecutive utterances by speaker)
WITH speaker_groups AS (
    SELECT 
        case_id,
        utterance_index,
        speaker_name,
        text,
        vector,
        token_count,
        LAG(speaker_name) OVER (PARTITION BY case_id ORDER BY utterance_index) as prev_speaker,
        SUM(CASE WHEN speaker_name != LAG(speaker_name) OVER (PARTITION BY case_id ORDER BY utterance_index) 
            THEN 1 ELSE 0 END) OVER (PARTITION BY case_id ORDER BY utterance_index) as speaker_group
    FROM scotustician.utterance_embeddings
    WHERE case_id = '2023_smith-v-jones'
)
SELECT 
    speaker_group,
    speaker_name,
    array_agg(utterance_index ORDER BY utterance_index) as utterances,
    SUM(token_count) as total_tokens,
    COUNT(*) as utterance_count
FROM speaker_groups
GROUP BY case_id, speaker_group, speaker_name
ORDER BY MIN(utterance_index);

-- 4. Time-based chunking (if timestamps are available)
WITH time_windows AS (
    SELECT 
        case_id,
        utterance_index,
        start_time_ms,
        end_time_ms,
        FLOOR(start_time_ms / 60000) as minute_bucket, -- 1-minute windows
        text,
        vector
    FROM scotustician.utterance_embeddings
    WHERE case_id = '2023_smith-v-jones'
    AND start_time_ms IS NOT NULL
)
SELECT 
    minute_bucket,
    MIN(start_time_ms) as window_start,
    MAX(end_time_ms) as window_end,
    array_agg(utterance_index ORDER BY utterance_index) as utterances,
    COUNT(*) as utterance_count
FROM time_windows
GROUP BY case_id, minute_bucket;

-- 5. Get embeddings with metadata for custom chunking algorithms
SELECT 
    u.utterance_index,
    u.speaker_name,
    u.text,
    u.vector,
    u.word_count,
    u.token_count,
    u.char_start_offset,
    u.char_end_offset,
    u.embedding_model,
    u.embedding_dimension,
    t.term,
    t.case_name
FROM scotustician.utterance_embeddings u
JOIN scotustician.transcript_embeddings t ON u.case_id = t.case_id
WHERE u.case_id = '2023_smith-v-jones'
ORDER BY u.utterance_index;