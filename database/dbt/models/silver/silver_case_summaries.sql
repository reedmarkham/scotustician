{{
  config(
    materialized='view'
  )
}}

WITH utterance_stats AS (
    SELECT
        case_id,
        oa_id,
        COUNT(DISTINCT utterance_id) AS total_utterances,
        COUNT(DISTINCT speaker_name) AS unique_speakers,
        SUM(word_count) AS total_words,
        SUM(token_count) AS total_tokens,
        AVG(duration_seconds) AS avg_utterance_duration,
        MAX(end_time_ms) / 1000.0 AS total_duration_seconds,
        MIN(created_at) AS first_utterance_created,
        MAX(created_at) AS last_utterance_created
    FROM {{ ref('bronze_oa_text') }}
    GROUP BY case_id, oa_id
),

speaker_breakdown AS (
    SELECT
        case_id,
        oa_id,
        COUNT(CASE WHEN speaker_role = 'Justice' THEN 1 END) AS justice_utterances,
        COUNT(CASE WHEN speaker_role = 'Chief Justice' THEN 1 END) AS chief_justice_utterances,
        COUNT(CASE WHEN speaker_role = 'Attorney' THEN 1 END) AS attorney_utterances,
        COUNT(CASE WHEN speaker_role = 'Solicitor General' THEN 1 END) AS solicitor_general_utterances
    FROM {{ ref('bronze_oa_text') }}
    GROUP BY case_id, oa_id
),

embedding_stats AS (
    SELECT
        case_id,
        COUNT(*) AS total_embeddings,
        AVG(text_length) AS avg_embedding_text_length,
        MAX(speaker_count) AS max_speakers_in_embedding
    FROM {{ ref('bronze_transcript_embeddings') }}
    GROUP BY case_id
)

SELECT
    u.case_id,
    u.oa_id,
    u.total_utterances,
    u.unique_speakers,
    u.total_words,
    u.total_tokens,
    u.avg_utterance_duration,
    u.total_duration_seconds,
    u.total_duration_seconds / 60.0 AS total_duration_minutes,
    s.justice_utterances,
    s.chief_justice_utterances,
    s.attorney_utterances,
    s.solicitor_general_utterances,
    e.total_embeddings,
    e.avg_embedding_text_length,
    e.max_speakers_in_embedding,
    u.first_utterance_created,
    u.last_utterance_created
FROM utterance_stats u
LEFT JOIN speaker_breakdown s 
    ON u.case_id = s.case_id 
    AND u.oa_id = s.oa_id
LEFT JOIN embedding_stats e 
    ON u.case_id = e.case_id