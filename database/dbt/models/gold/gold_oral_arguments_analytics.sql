{{
  config(
    materialized='table',
    indexes=[
      {'columns': ['case_id'], 'type': 'btree'},
      {'columns': ['oa_id'], 'type': 'btree'},
      {'columns': ['total_duration_minutes'], 'type': 'btree'}
    ]
  )
}}

WITH case_info AS (
    SELECT DISTINCT
        case_id,
        case_name,
        term
    FROM {{ ref('bronze_transcript_embeddings') }}
    WHERE case_name IS NOT NULL
),

case_metrics AS (
    SELECT * FROM {{ ref('silver_case_summaries') }}
)

SELECT
    ci.case_id,
    ci.case_name,
    ci.term,
    cm.oa_id,
    cm.total_utterances,
    cm.unique_speakers,
    cm.total_words,
    cm.total_tokens,
    cm.total_duration_minutes,
    cm.avg_utterance_duration,
    -- Speaker participation ratios
    ROUND(cm.justice_utterances::numeric / NULLIF(cm.total_utterances, 0) * 100, 2) AS justice_participation_pct,
    ROUND(cm.attorney_utterances::numeric / NULLIF(cm.total_utterances, 0) * 100, 2) AS attorney_participation_pct,
    -- Engagement metrics
    ROUND(cm.total_utterances::numeric / NULLIF(cm.total_duration_minutes, 0), 2) AS utterances_per_minute,
    ROUND(cm.total_words::numeric / NULLIF(cm.total_duration_minutes, 0), 2) AS words_per_minute,
    -- Embedding coverage
    cm.total_embeddings,
    cm.avg_embedding_text_length,
    -- Timestamps
    cm.first_utterance_created,
    cm.last_utterance_created,
    CURRENT_TIMESTAMP AS updated_at
FROM case_info ci
INNER JOIN case_metrics cm 
    ON ci.case_id = cm.case_id
ORDER BY ci.term DESC, ci.case_name