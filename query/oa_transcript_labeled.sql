DROP TABLE if exists public.oa_transcript_labeled;
CREATE TABLE if not exists public.oa_transcript_labeled
(
    case_id text COLLATE pg_catalog."default" NOT NULL,
    term text COLLATE pg_catalog."default" NOT NULL,
    docket_number text COLLATE pg_catalog."default" NOT NULL,
    case_name text COLLATE pg_catalog."default" NOT NULL,
    oa_id text COLLATE pg_catalog."default" NOT NULL,
    oa_title text COLLATE pg_catalog."default" NOT NULL,
    oa_session integer NOT NULL,
    speaker_id text COLLATE pg_catalog."default",
    speaker_name text COLLATE pg_catalog."default",
    role text COLLATE pg_catalog."default",
    start numeric NOT NULL,
    stop numeric NOT NULL,
    text_block text COLLATE pg_catalog."default" NOT NULL,
    word_count integer
)
TABLESPACE pg_default;

ALTER TABLE public.oa_transcript_labeled
    OWNER to postgres;

insert into public.oa_transcript_labeled(case_id, term, docket_number, case_name, oa_id, oa_title, oa_session, speaker_id, speaker_name, role, start, stop, text_block, word_count)
select distinct
c.case_id,
c.term,
c.docket_number,
c.case_name,
t.oa_id,
c.oa_title,
t.oa_session,
t.speaker_id,
coalesce(s.speaker_name,'N/A') as speaker_name,
coalesce(s.role, 'N/A') as role,
t.start,
t.stop,
t.text_block,
t.word_count
from
(
select
oa_id,
oa_session,
coalesce(speaker_id, 'N/A') as speaker_id,
start,
stop,
text_block,
sum(array_length(regexp_split_to_array(text_block, '\s'),1)) as word_count
from public.oa_transcript
group by
oa_id,
oa_session,
coalesce(speaker_id, 'N/A'),
start,
stop,
text_block
) t
left join
(
select speaker_id, speaker_name, coalesce(roles->(jsonb_array_length(roles)-1)->>'role_title','Advocate') as role from public.speakers
) s
on t.speaker_id = s.speaker_id
left join
(
select oa_id, oa_title, case_id, term, docket_number, case_name from public.oa_to_case
) c
on t.oa_id = c.oa_id
;

CREATE INDEX IF NOT EXISTS oa_transcript_labeled_oa_id_index ON public.oa_transcript_labeled(oa_id);
CREATE INDEX IF NOT EXISTS oa_transcript_labeled_case_id_index ON public.oa_transcript_labeled(case_id);
CREATE INDEX IF NOT EXISTS oa_transcript_labeled_term_index ON public.oa_transcript_labeled(term);
CREATE INDEX IF NOT EXISTS oa_transcript_labeled_speaker_id_index ON public.oa_transcript_labeled(speaker_id);