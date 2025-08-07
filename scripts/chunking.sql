-- Example queries for working with document chunk embeddings from the new schema

-- 1. Get all document chunks for a case with their embeddings
SELECT 
    section_id,
    chunk_text,
    vector,
    word_count,
    token_count,
    start_utterance_index,
    end_utterance_index,
    embedding_model,
    embedding_dimension
FROM scotustician.document_chunk_embeddings
WHERE case_id = '2023_smith-v-jones'
ORDER BY section_id;

-- 2. Get raw utterance text with associated chunk information
SELECT 
    t.utterance_index,
    t.speaker_name,
    t.text,
    t.word_count,
    t.token_count,
    t.start_time_ms,
    t.end_time_ms,
    c.section_id,
    c.chunk_text
FROM scotustician.oa_text t
LEFT JOIN scotustician.document_chunk_embeddings c 
    ON t.case_id = c.case_id 
    AND t.utterance_index BETWEEN c.start_utterance_index AND c.end_utterance_index
WHERE t.case_id = '2023_smith-v-jones'
ORDER BY t.utterance_index;

-- 3. Analyze chunking distribution (sections per case)
SELECT 
    case_id,
    COUNT(DISTINCT section_id) as num_sections,
    SUM(word_count) as total_words,
    SUM(token_count) as total_tokens,
    AVG(token_count) as avg_tokens_per_section,
    MAX(token_count) as max_section_tokens,
    MIN(token_count) as min_section_tokens
FROM scotustician.document_chunk_embeddings
GROUP BY case_id
ORDER BY num_sections DESC;

-- 4. Find similar sections across different cases using vector similarity
-- (Assuming pgvector extension is installed)
WITH target_section AS (
    SELECT vector 
    FROM scotustician.document_chunk_embeddings 
    WHERE case_id = '2023_smith-v-jones' AND section_id = 0
)
SELECT 
    d.case_id,
    d.section_id,
    d.chunk_text,
    d.vector <-> t.vector AS distance  -- cosine distance
FROM scotustician.document_chunk_embeddings d, target_section t
WHERE d.case_id != '2023_smith-v-jones'
ORDER BY distance
LIMIT 10;

-- 5. Speaker statistics per section
SELECT 
    c.case_id,
    c.section_id,
    t.speaker_name,
    COUNT(DISTINCT t.utterance_index) as utterance_count,
    SUM(t.word_count) as total_words,
    AVG(t.word_count) as avg_words_per_utterance
FROM scotustician.document_chunk_embeddings c
JOIN scotustician.oa_text t 
    ON c.case_id = t.case_id 
    AND t.utterance_index BETWEEN c.start_utterance_index AND c.end_utterance_index
GROUP BY c.case_id, c.section_id, t.speaker_name
ORDER BY c.case_id, c.section_id, utterance_count DESC;

-- 6. Time-based analysis (if timestamps are available)
SELECT 
    c.case_id,
    c.section_id,
    MIN(t.start_time_ms) as section_start_ms,
    MAX(t.end_time_ms) as section_end_ms,
    (MAX(t.end_time_ms) - MIN(t.start_time_ms)) / 1000.0 as section_duration_seconds
FROM scotustician.document_chunk_embeddings c
JOIN scotustician.oa_text t 
    ON c.case_id = t.case_id 
    AND t.utterance_index BETWEEN c.start_utterance_index AND c.end_utterance_index
WHERE t.start_time_ms IS NOT NULL
GROUP BY c.case_id, c.section_id
ORDER BY c.case_id, c.section_id;

-- 7. Search for specific content within chunks
SELECT 
    case_id,
    section_id,
    chunk_text,
    word_count,
    token_count
FROM scotustician.document_chunk_embeddings
WHERE chunk_text ILIKE '%first amendment%'
ORDER BY case_id, section_id;

-- 8. Get metadata about the embedding models used
SELECT 
    embedding_model,
    embedding_dimension,
    COUNT(DISTINCT case_id) as cases_processed,
    COUNT(*) as total_chunks,
    AVG(token_count) as avg_tokens_per_chunk
FROM scotustician.document_chunk_embeddings
GROUP BY embedding_model, embedding_dimension;

-- 9. Find cases with unusual section patterns
WITH section_stats AS (
    SELECT 
        case_id,
        COUNT(DISTINCT section_id) as section_count,
        MAX(section_id) + 1 as expected_sections
    FROM scotustician.document_chunk_embeddings
    GROUP BY case_id
)
SELECT 
    case_id,
    section_count,
    expected_sections,
    CASE 
        WHEN section_count != expected_sections THEN 'Missing sections'
        WHEN section_count < 2 THEN 'Too few sections'
        WHEN section_count > 5 THEN 'Many sections'
        ELSE 'Normal'
    END as pattern
FROM section_stats
WHERE section_count != expected_sections 
   OR section_count < 2 
   OR section_count > 5
ORDER BY section_count DESC;

-- 10. Export chunks for external processing (e.g., fine-tuning)
SELECT 
    c.case_id,
    c.oa_id,
    c.section_id,
    c.chunk_text,
    c.word_count,
    c.token_count,
    array_to_json(c.vector) as embedding_json
FROM scotustician.document_chunk_embeddings c
WHERE c.case_id IN (
    SELECT case_id 
    FROM scotustician.document_chunk_embeddings 
    GROUP BY case_id 
    HAVING COUNT(*) >= 3  -- Only cases with at least 3 sections
    LIMIT 100
)
ORDER BY c.case_id, c.section_id;