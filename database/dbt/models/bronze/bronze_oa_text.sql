{{
  config(
    materialized='view'
  )
}}

WITH source AS (
    SELECT * FROM {{ source('scotustician', 'oa_text') }}
),

bronze AS (
    SELECT
        id AS utterance_id,
        case_id,
        oa_id,
        utterance_index,
        speaker_id,
        speaker_name,
        text AS utterance_text,
        word_count,
        token_count,
        start_time_ms,
        end_time_ms,
        char_start_offset,
        char_end_offset,
        source_key,
        created_at,
        -- Add computed columns
        CASE 
            WHEN start_time_ms IS NOT NULL AND end_time_ms IS NOT NULL 
            THEN (end_time_ms - start_time_ms) / 1000.0
            ELSE NULL
        END AS duration_seconds,
        CASE
            WHEN speaker_name ILIKE '%JUSTICE%' THEN 'Justice'
            WHEN speaker_name ILIKE '%CHIEF%' THEN 'Chief Justice'
            WHEN speaker_name ILIKE '%GENERAL%' THEN 'Solicitor General'
            ELSE 'Attorney'
        END AS speaker_role
    FROM source
)

SELECT * FROM bronze