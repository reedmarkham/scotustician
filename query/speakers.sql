DROP TABLE if exists public.speakers;
CREATE TABLE if not exists public.speakers
(
    speaker jsonb NOT NULL,
    speaker_id text COLLATE pg_catalog."default",
    identifier text COLLATE pg_catalog."default",
    speaker_name text COLLATE pg_catalog."default",
    last_name text COLLATE pg_catalog."default",
    roles jsonb
)
TABLESPACE pg_default;

ALTER TABLE public.speakers
    OWNER to postgres;

insert into public.speakers(speaker, speaker_id, identifier, speaker_name, last_name, roles)
select distinct
speaker,
speaker->>'ID',
speaker->>'identifier',
speaker->>'name',
speaker->>'last_name',
case when jsonb_typeof(speaker->'roles') = 'array' then speaker->'roles' else jsonb_build_array(speaker->'roles') end
from
(
select 
jsonb_array_elements(jsonb_array_elements(raw_file->'transcript'->'sections')->'turns')->'speaker' as speaker
from raw.oa
) s1
where (speaker != 'null' and speaker is not null)
;

CREATE INDEX IF NOT EXISTS speakers_speaker_id_index ON public.speakers(speaker_id);