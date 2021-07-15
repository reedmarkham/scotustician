CREATE SCHEMA IF NOT EXISTS "raw"
    AUTHORIZATION postgres;

CREATE TABLE IF NOT EXISTS "raw".case_full
(
    s3_key text COLLATE pg_catalog."default" NOT NULL,
    last_updated text COLLATE pg_catalog."default" NOT NULL,
    raw_file jsonb NOT NULL,
    CONSTRAINT case_full_pkey PRIMARY KEY (s3_key)
)

TABLESPACE pg_default;

ALTER TABLE "raw".case_full
    OWNER to postgres;

CREATE TABLE IF NOT EXISTS "raw".case_summary
(
    s3_key text COLLATE pg_catalog."default" NOT NULL,
    last_updated text COLLATE pg_catalog."default" NOT NULL,
    raw_file jsonb NOT NULL,
    CONSTRAINT case_summary_pkey PRIMARY KEY (s3_key)
)

TABLESPACE pg_default;

ALTER TABLE "raw".case_summary
    OWNER to postgres;

CREATE TABLE IF NOT EXISTS "raw".oa
(
    s3_key text COLLATE pg_catalog."default" NOT NULL,
    last_updated text COLLATE pg_catalog."default" NOT NULL,
    raw_file jsonb NOT NULL,
    CONSTRAINT oa_pkey PRIMARY KEY (s3_key)
)

TABLESPACE pg_default;

ALTER TABLE "raw".oa
    OWNER to postgres;