DROP TABLE if exists public.word_count_per_case;
CREATE TABLE if not exists public.word_count_per_case
(
    case_id text COLLATE pg_catalog."default" NOT NULL,
    term text COLLATE pg_catalog."default" NOT NULL,
    docket_number text COLLATE pg_catalog."default" NOT NULL,
    case_name text COLLATE pg_catalog."default" NOT NULL,
    speaker_id text COLLATE pg_catalog."default",
    speaker_name text COLLATE pg_catalog."default",
    word_count integer
)
TABLESPACE pg_default;

ALTER TABLE public.word_count_per_case
    OWNER to postgres;

insert into public.word_count_per_case(case_id, term, docket_number, case_name, speaker_id, speaker_name, role, word_count)
select
case_id,
term,
docket_number,
case_name,
speaker_id,
speaker_name,
role,
sum(word_count) as word_count
from public.oa_transcript_labeled
group by
case_id,
term,
docket_number,
case_name,
speaker_id,
speaker_name,
role
;