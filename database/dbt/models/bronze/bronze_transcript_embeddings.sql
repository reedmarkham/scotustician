{{
  config(
    materialized='view'
  )
}}

WITH source AS (
    SELECT * FROM {{ source('scotustician', 'transcript_embeddings') }}
),

bronze AS (
    SELECT
        id AS embedding_id,
        text AS embedding_text,
        vector AS embedding_vector,
        case_name,
        term,
        case_id,
        oa_id,
        source_key,
        xml_uri,
        speaker_list,
        created_at,
        updated_at,
        -- Add computed columns
        LENGTH(text) AS text_length,
        COALESCE(jsonb_array_length(speaker_list), 0) AS speaker_count
    FROM source
)

SELECT * FROM bronze