DROP TABLE if exists public.oa_to_case;
CREATE TABLE if not exists public.oa_to_case
(
    case_id text COLLATE pg_catalog."default" NOT NULL,
    case_name text COLLATE pg_catalog."default" NOT NULL,
    term text COLLATE pg_catalog."default" NOT NULL,
    docket_number text COLLATE pg_catalog."default" NOT NULL,
    oa_id text COLLATE pg_catalog."default" NOT NULL,
    oa_title text COLLATE pg_catalog."default" NOT NULL
)
TABLESPACE pg_default;

ALTER TABLE public.oa_to_case
    OWNER to postgres;

insert into public.oa_to_case(case_id, case_name, term, docket_number, oa_id, oa_title)
select distinct
case_id,
case_name,
term,
docket_number,
oral_argument_audio->>'id' as oa_id,
oral_argument_audio->>'title' as oa_title
from 
(
select 
raw_file->>'ID' as case_id,
raw_file->>'name' as case_name,
raw_file->>'term' as term,
raw_file->>'docket_number' as docket_number,
jsonb_array_elements(case when jsonb_typeof(raw_file->'oral_argument_audio') = 'array' then raw_file->'oral_argument_audio' else jsonb_build_array(raw_file->'oral_argument_audio') end) as oral_argument_audio,
raw_file
from raw.case_full 
) c
where (oral_argument_audio is not null and oral_argument_audio != 'null')
;