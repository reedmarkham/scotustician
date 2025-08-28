{% macro get_term_year(term_string) %}
  -- Extract year from term string (e.g., "2023" from "2023-24" or "OT2023")
  CASE 
    WHEN {{ term_string }} ~ '^\d{4}' 
    THEN SUBSTRING({{ term_string }} FROM '^\d{4}')::INTEGER
    WHEN {{ term_string }} ~ 'OT\d{4}' 
    THEN SUBSTRING({{ term_string }} FROM 'OT(\d{4})')::INTEGER
    ELSE NULL
  END
{% endmacro %}