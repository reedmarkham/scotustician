{{
  config(
    materialized='table',
    indexes=[
      {'columns': ['speaker_name'], 'type': 'btree'},
      {'columns': ['case_id'], 'type': 'btree'},
      {'columns': ['total_utterances'], 'type': 'btree'}
    ]
  )
}}

WITH speaker_stats AS (
    SELECT
        speaker_name,
        speaker_role,
        case_id,
        oa_id,
        COUNT(*) AS total_utterances,
        SUM(word_count) AS total_words,
        SUM(token_count) AS total_tokens,
        AVG(word_count) AS avg_words_per_utterance,
        SUM(duration_seconds) AS total_speaking_time,
        AVG(duration_seconds) AS avg_utterance_duration,
        MIN(utterance_index) AS first_utterance_index,
        MAX(utterance_index) AS last_utterance_index
    FROM {{ ref('bronze_oa_text') }}
    WHERE speaker_name IS NOT NULL
    GROUP BY speaker_name, speaker_role, case_id, oa_id
),

case_context AS (
    SELECT DISTINCT
        case_id,
        case_name,
        term
    FROM {{ ref('bronze_transcript_embeddings') }}
)

SELECT
    ss.speaker_name,
    ss.speaker_role,
    ss.case_id,
    cc.case_name,
    cc.term,
    ss.oa_id,
    ss.total_utterances,
    ss.total_words,
    ss.total_tokens,
    ss.avg_words_per_utterance,
    ROUND(ss.total_speaking_time / 60.0, 2) AS total_speaking_minutes,
    ss.avg_utterance_duration,
    -- Engagement patterns
    (ss.last_utterance_index - ss.first_utterance_index + 1) AS utterance_span,
    CASE 
        WHEN ss.total_utterances > 1 
        THEN ROUND((ss.last_utterance_index - ss.first_utterance_index)::numeric / (ss.total_utterances - 1), 2)
        ELSE 0 
    END AS avg_utterance_gap,
    -- Words per minute (if duration available)
    CASE 
        WHEN ss.total_speaking_time > 0 
        THEN ROUND(ss.total_words::numeric / (ss.total_speaking_time / 60.0), 2)
        ELSE NULL 
    END AS words_per_minute,
    CURRENT_TIMESTAMP AS updated_at
FROM speaker_stats ss
LEFT JOIN case_context cc 
    ON ss.case_id = cc.case_id
ORDER BY ss.total_utterances DESC