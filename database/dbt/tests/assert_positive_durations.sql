-- Test to ensure all durations are positive when present
SELECT *
FROM {{ ref('bronze_oa_text') }}
WHERE duration_seconds IS NOT NULL 
  AND duration_seconds <= 0