{{
  config(
    materialized='view'
  )
}}

WITH source AS (
    SELECT * FROM {{ source('scotustician', 'document_chunk_embeddings') }}
),

bronze AS (
    SELECT
        id AS chunk_id,
        case_id,
        oa_id,
        section_id,
        chunk_text,
        vector AS chunk_vector,
        word_count,
        token_count,
        start_utterance_index,
        end_utterance_index,
        embedding_model,
        embedding_dimension,
        source_key,
        created_at,
        -- Add computed columns
        (end_utterance_index - start_utterance_index + 1) AS utterance_span,
        LENGTH(chunk_text) AS chunk_length
    FROM source
)

SELECT * FROM bronze