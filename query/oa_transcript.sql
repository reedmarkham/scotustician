DROP TABLE IF EXISTS public.oa_transcript;
CREATE TABLE IF NOT EXISTS public.oa_transcript
(
    oa_id text COLLATE pg_catalog."default" NOT NULL,
    oa_session integer NOT NULL,
    speaker_id text COLLATE pg_catalog."default",
    start numeric NOT NULL,
    stop numeric NOT NULL,
    text_block text COLLATE pg_catalog."default" NOT NULL
)
TABLESPACE pg_default;

ALTER TABLE public.oa_transcript
    OWNER to postgres;

INSERT INTO public.oa_transcript(oa_id, oa_session, speaker_id, start, stop, text_block)
select distinct
raw_file->>'id', 
ordinality,
jsonb_array_elements(jsonb_array_elements(raw_file->'transcript'->'sections')->'turns')->'speaker'->>'ID', 
cast(jsonb_array_elements(jsonb_array_elements(jsonb_array_elements(raw_file->'transcript'->'sections')->'turns')->'text_blocks')->>'start' as numeric),
cast(jsonb_array_elements(jsonb_array_elements(jsonb_array_elements(raw_file->'transcript'->'sections')->'turns')->'text_blocks')->>'stop' as numeric), 
jsonb_array_elements(jsonb_array_elements(jsonb_array_elements(raw_file->'transcript'->'sections')->'turns')->'text_blocks')->>'text'
from raw.oa, jsonb_array_elements(raw_file->'transcript'->'sections') with ordinality
;

CREATE INDEX IF NOT EXISTS oa_transcript_oa_id_index ON public.oa_transcript(oa_id);