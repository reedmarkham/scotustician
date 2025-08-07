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

-- 3. Section-level token analysis for monitoring (similar to JSON analysis)
WITH section_analysis AS (
    SELECT 
        c.case_id,
        c.oa_id,
        c.section_id,
        c.token_count,
        c.word_count,
        (c.end_utterance_index - c.start_utterance_index + 1) as utterance_count,
        COUNT(t.id) as text_blocks,
        -- Calculate duration from utterance timing
        (MAX(t.end_time_ms) - MIN(t.start_time_ms))::float / 1000.0 / 60.0 as duration_minutes,
        LENGTH(c.chunk_text) as character_count
    FROM scotustician.document_chunk_embeddings c
    LEFT JOIN scotustician.oa_text t 
        ON c.case_id = t.case_id 
        AND t.utterance_index BETWEEN c.start_utterance_index AND c.end_utterance_index
    GROUP BY c.case_id, c.oa_id, c.section_id, c.token_count, c.word_count, 
             c.start_utterance_index, c.end_utterance_index, c.chunk_text
)
SELECT 
    'Section ' || (section_id + 1) as section_label,
    ROUND(COALESCE(duration_minutes, 0)::numeric, 1) as duration_min,
    utterance_count as turns,
    text_blocks,
    character_count as est_chars,
    token_count as est_tokens,
    CASE 
        WHEN token_count > 6000 THEN 'LARGE - Consider splitting'
        WHEN token_count > 4000 THEN 'Large'
        WHEN token_count < 1500 THEN 'Small'
        ELSE 'Normal'
    END as size_assessment
FROM section_analysis
WHERE case_id = (
    -- Get most recent case for monitoring
    SELECT case_id 
    FROM scotustician.document_chunk_embeddings 
    ORDER BY created_at DESC 
    LIMIT 1
)
ORDER BY section_id;

-- Summary statistics across all cases
SELECT 
    'OVERALL STATS' as analysis_type,
    COUNT(DISTINCT case_id) as total_cases,
    COUNT(*) as total_sections,
    ROUND(AVG(token_count)::numeric, 0) as avg_tokens_per_section,
    MIN(token_count) as min_tokens,
    MAX(token_count) as max_tokens,
    ROUND(STDDEV(token_count)::numeric, 0) as token_stddev,
    -- Token distribution analysis
    COUNT(CASE WHEN token_count < 2000 THEN 1 END) as sections_under_2k,
    COUNT(CASE WHEN token_count BETWEEN 2000 AND 4000 THEN 1 END) as sections_2k_4k,
    COUNT(CASE WHEN token_count BETWEEN 4000 AND 6000 THEN 1 END) as sections_4k_6k,
    COUNT(CASE WHEN token_count > 6000 THEN 1 END) as sections_over_6k
FROM scotustician.document_chunk_embeddings;

-- Section role classification based on oral argument structure
WITH section_roles AS (
    SELECT 
        case_id,
        oa_id,
        section_id,
        token_count,
        -- Get first speaker to help identify role
        (
            SELECT DISTINCT t.speaker_name 
            FROM scotustician.oa_text t 
            WHERE t.case_id = c.case_id 
              AND t.utterance_index = c.start_utterance_index
            LIMIT 1
        ) as first_speaker,
        -- Count sections per case to determine pattern
        COUNT(*) OVER (PARTITION BY case_id) as total_sections,
        -- Classify role based on section_id and total sections
        CASE 
            -- Simple 3-section pattern: Petitioner -> Respondent -> Petitioner Rebuttal
            WHEN COUNT(*) OVER (PARTITION BY case_id) = 3 THEN
                CASE section_id 
                    WHEN 0 THEN 'Petitioner Opening'
                    WHEN 1 THEN 'Respondent'  
                    WHEN 2 THEN 'Petitioner Rebuttal'
                END
            -- 4-section pattern: Petitioner -> Respondent -> Respondent #2 -> Petitioner Rebuttal
            WHEN COUNT(*) OVER (PARTITION BY case_id) = 4 THEN
                CASE section_id
                    WHEN 0 THEN 'Petitioner Opening'
                    WHEN 1 THEN 'Respondent (Primary)'
                    WHEN 2 THEN 'Respondent (Secondary)'
                    WHEN 3 THEN 'Petitioner Rebuttal'
                END
            -- 5-section pattern (like Plyler v. Doe): Pet -> Resp #1 -> Resp #2 -> Resp #3 -> Pet Rebuttal
            WHEN COUNT(*) OVER (PARTITION BY case_id) = 5 THEN
                CASE section_id
                    WHEN 0 THEN 'Petitioner Opening'
                    WHEN 1 THEN 'Respondent #1'
                    WHEN 2 THEN 'Respondent #2' 
                    WHEN 3 THEN 'Respondent #3'
                    WHEN 4 THEN 'Petitioner Rebuttal'
                END
            -- 6+ sections: More complex cases with government or amicus participation
            WHEN COUNT(*) OVER (PARTITION BY case_id) >= 6 THEN
                CASE 
                    WHEN section_id = 0 THEN 'Petitioner Opening'
                    WHEN section_id = (COUNT(*) OVER (PARTITION BY case_id) - 1) THEN 'Petitioner Rebuttal'
                    ELSE 'Respondent/Amicus #' || section_id
                END
            -- 1-2 sections: Unusual cases
            ELSE 'Section ' || (section_id + 1)
        END as argument_role,
        -- Additional context
        CASE 
            WHEN section_id = 0 THEN 'Opening'
            WHEN section_id = (COUNT(*) OVER (PARTITION BY case_id) - 1) AND token_count < 2000 THEN 'Rebuttal'
            ELSE 'Main Argument'
        END as argument_phase
    FROM scotustician.document_chunk_embeddings c
)
SELECT 
    case_id,
    oa_id,
    'Section ' || (section_id + 1) as section_label,
    argument_role,
    argument_phase,
    first_speaker,
    token_count,
    total_sections,
    CASE 
        WHEN argument_role LIKE '%Rebuttal%' AND token_count > 2500 THEN 'Long rebuttal - unusual'
        WHEN argument_role LIKE '%Opening%' AND token_count < 2000 THEN 'Short opening - check for issues'  
        WHEN argument_role LIKE '%Respondent%' AND token_count > 6000 THEN 'Very long argument - consider splitting'
        ELSE 'Normal'
    END as assessment
FROM section_roles
ORDER BY case_id DESC, section_id;

-- Summary of argument patterns across all cases
SELECT 
    total_sections,
    COUNT(DISTINCT case_id) as case_count,
    ROUND(AVG(token_count)::numeric, 0) as avg_tokens_per_section,
    STRING_AGG(DISTINCT 
        CASE section_id
            WHEN 0 THEN 'Opening'
            WHEN total_sections - 1 THEN 'Rebuttal' 
            ELSE 'Main-' || section_id
        END, 
        ' → ' ORDER BY section_id
    ) as typical_pattern
FROM (
    SELECT 
        case_id,
        section_id, 
        token_count,
        COUNT(*) OVER (PARTITION BY case_id) as total_sections
    FROM scotustician.document_chunk_embeddings
) patterns
GROUP BY total_sections
ORDER BY case_count DESC;

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