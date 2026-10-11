-- Imported catalogue snapshots. Format {catalogue_schema} with psycopg.sql.Identifier.
-- vector is installed in public by backend initialization; 001 evidence is not rebuilt.
CREATE SCHEMA IF NOT EXISTS {catalogue_schema};
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE TYPE {catalogue_schema}.ktru_status AS ENUM ('ACTIVE', 'INACTIVE', 'TERMINATED');

CREATE TYPE {catalogue_schema}.value_choice AS ENUM ('fixed', 'one_of', 'many_of');

CREATE TYPE {catalogue_schema}.spgz_role AS ENUM ('base', 'reference', 'category');

CREATE TYPE {catalogue_schema}.spgz_vtype AS ENUM ('text', 'dict', 'flag', 'int', 'decimal', 'range');

CREATE FUNCTION {catalogue_schema}.norm(t text) RETURNS text
    IMMUTABLE LANGUAGE sql
    AS $$ SELECT btrim(regexp_replace(replace(lower(t), 'ё', 'е'), '\s+', ' ', 'g')) $$;

CREATE TABLE {catalogue_schema}.catalogue_imports (
	sha256 TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	metadata JSONB DEFAULT '{{}}'::jsonb NOT NULL,
	PRIMARY KEY (sha256)
);

CREATE TABLE {catalogue_schema}.embedding_configs (
	fingerprint TEXT NOT NULL,
	model TEXT NOT NULL,
	dimensions INTEGER NOT NULL,
	document_prompt TEXT NOT NULL,
	query_prompt TEXT NOT NULL,
	document_format TEXT NOT NULL,
	PRIMARY KEY (fingerprint),
	CHECK (dimensions = 768)
);

CREATE TABLE {catalogue_schema}.okei (
	code TEXT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (code)
);

CREATE TABLE {catalogue_schema}.okpd2 (
	code TEXT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (code)
);

CREATE TABLE {catalogue_schema}.catalogue_sources (
	key TEXT NOT NULL,
	import_sha256 TEXT NOT NULL,
	PRIMARY KEY (key),
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.kpgz (
	import_sha256 TEXT NOT NULL,
	code TEXT NOT NULL,
	name TEXT NOT NULL,
	category TEXT NOT NULL,
	PRIMARY KEY (import_sha256, code),
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.okei_alias (
	alias TEXT NOT NULL,
	okei TEXT NOT NULL,
	PRIMARY KEY (alias),
	FOREIGN KEY(okei) REFERENCES {catalogue_schema}.okei (code) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE {catalogue_schema}.source_files (
	id BIGINT GENERATED ALWAYS AS IDENTITY,
	import_sha256 TEXT NOT NULL,
	name TEXT NOT NULL,
	sha256 TEXT NOT NULL,
	kind TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (import_sha256, name),
	UNIQUE (import_sha256, id),
	CHECK (kind IN ('xml', 'xlsx')),
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.spgz_ref (
	import_sha256 TEXT NOT NULL,
	id BIGINT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (import_sha256, id),
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.ktru_position (
	import_sha256 TEXT NOT NULL,
	code TEXT NOT NULL,
	version INTEGER NOT NULL,
	xml_id TEXT,
	version_code TEXT,
	external_code TEXT,
	updated TIMESTAMP WITH TIME ZONE NOT NULL,
	name TEXT NOT NULL,
	okpd2 TEXT NOT NULL,
	status {catalogue_schema}.ktru_status NOT NULL,
	terminated_on DATE,
	is_template BOOLEAN NOT NULL,
	parent_code TEXT,
	parent_version INTEGER,
	applies_from DATE NOT NULL,
	applies_to DATE,
	no_new_features BOOLEAN,
	no_new_features_reason TEXT,
	units TEXT[] NOT NULL,
	rubrics TEXT[] NOT NULL,
	rubric_codes TEXT[] NOT NULL,
	description TEXT,
	source_file_id BIGINT NOT NULL,
	source_line INTEGER NOT NULL,
	embedding public.vector(768),
	embedding_config TEXT,
	PRIMARY KEY (import_sha256, code),
	FOREIGN KEY(import_sha256, source_file_id) REFERENCES {catalogue_schema}.source_files (import_sha256, id) DEFERRABLE INITIALLY DEFERRED,
	CHECK (parent_version IS NULL OR parent_code IS NOT NULL),
	CHECK ((embedding IS NULL) = (embedding_config IS NULL)),
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256),
	FOREIGN KEY(okpd2) REFERENCES {catalogue_schema}.okpd2 (code) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(embedding_config) REFERENCES {catalogue_schema}.embedding_configs (fingerprint)
);

CREATE TABLE {catalogue_schema}.spgz_ref_value (
	import_sha256 TEXT NOT NULL,
	ref_id BIGINT NOT NULL,
	text TEXT NOT NULL,
	PRIMARY KEY (import_sha256, ref_id, text),
	FOREIGN KEY(import_sha256, ref_id) REFERENCES {catalogue_schema}.spgz_ref (import_sha256, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE {catalogue_schema}.workbook (
	import_sha256 TEXT NOT NULL,
	id SMALLINT NOT NULL,
	name TEXT NOT NULL,
	source_file_id BIGINT NOT NULL,
	PRIMARY KEY (import_sha256, id),
	UNIQUE (import_sha256, name),
	FOREIGN KEY(import_sha256, source_file_id) REFERENCES {catalogue_schema}.source_files (import_sha256, id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.kpgz_characteristic (
	import_sha256 TEXT NOT NULL,
	id INTEGER NOT NULL,
	kpgz_code TEXT NOT NULL,
	name TEXT NOT NULL,
	role {catalogue_schema}.spgz_role NOT NULL,
	value_type {catalogue_schema}.spgz_vtype NOT NULL,
	unit TEXT,
	src_workbook SMALLINT NOT NULL,
	src_row INTEGER NOT NULL,
	PRIMARY KEY (import_sha256, id),
	FOREIGN KEY(import_sha256, kpgz_code) REFERENCES {catalogue_schema}.kpgz (import_sha256, code) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(import_sha256, src_workbook) REFERENCES {catalogue_schema}.workbook (import_sha256, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE {catalogue_schema}.ktru_characteristic (
	import_sha256 TEXT NOT NULL,
	position_code TEXT NOT NULL,
	code TEXT NOT NULL,
	name TEXT NOT NULL,
	is_numeric BOOLEAN NOT NULL,
	choice {catalogue_schema}.value_choice NOT NULL,
	required BOOLEAN NOT NULL,
	actual BOOLEAN NOT NULL,
	choice_type SMALLINT,
	embedding public.vector(768),
	embedding_config TEXT,
	PRIMARY KEY (import_sha256, position_code, code),
	FOREIGN KEY(import_sha256, position_code) REFERENCES {catalogue_schema}.ktru_position (import_sha256, code) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CHECK ((embedding IS NULL) = (embedding_config IS NULL)),
	FOREIGN KEY(embedding_config) REFERENCES {catalogue_schema}.embedding_configs (fingerprint)
);

CREATE TABLE {catalogue_schema}.ste (
	import_sha256 TEXT NOT NULL,
	id BIGINT NOT NULL,
	name TEXT NOT NULL,
	model TEXT,
	manufacturer TEXT,
	country TEXT,
	attrs TEXT[] NOT NULL,
	src_workbook SMALLINT NOT NULL,
	src_row INTEGER NOT NULL,
	PRIMARY KEY (import_sha256, id),
	FOREIGN KEY(import_sha256, src_workbook) REFERENCES {catalogue_schema}.workbook (import_sha256, id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(import_sha256) REFERENCES {catalogue_schema}.catalogue_imports (sha256)
);

CREATE TABLE {catalogue_schema}.kpgz_characteristic_ref (
	import_sha256 TEXT NOT NULL,
	characteristic_id INTEGER NOT NULL,
	ref_id BIGINT NOT NULL,
	PRIMARY KEY (import_sha256, characteristic_id, ref_id),
	FOREIGN KEY(import_sha256, characteristic_id) REFERENCES {catalogue_schema}.kpgz_characteristic (import_sha256, id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(import_sha256, ref_id) REFERENCES {catalogue_schema}.spgz_ref (import_sha256, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE {catalogue_schema}.kpgz_value (
	import_sha256 TEXT NOT NULL,
	characteristic_id INTEGER NOT NULL,
	text TEXT NOT NULL,
	PRIMARY KEY (import_sha256, characteristic_id, text),
	FOREIGN KEY(import_sha256, characteristic_id) REFERENCES {catalogue_schema}.kpgz_characteristic (import_sha256, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE {catalogue_schema}.ktru_value (
	id BIGINT GENERATED ALWAYS AS IDENTITY,
	import_sha256 TEXT NOT NULL,
	position_code TEXT NOT NULL,
	characteristic_code TEXT NOT NULL,
	ordinal INTEGER NOT NULL,
	code TEXT,
	text TEXT,
	spans NUMRANGE[],
	okei TEXT,
	issue TEXT,
	value_format TEXT,
	embedding public.vector(768),
	embedding_config TEXT,
	PRIMARY KEY (id),
	UNIQUE (import_sha256, position_code, characteristic_code, ordinal),
	FOREIGN KEY(import_sha256, position_code, characteristic_code) REFERENCES {catalogue_schema}.ktru_characteristic (import_sha256, position_code, code) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CHECK (ordinal >= 0),
	CHECK (text IS NULL OR spans IS NULL),
	CHECK (text IS NOT NULL OR spans IS NOT NULL OR issue IS NOT NULL),
	CHECK (spans IS NULL OR (array_ndims(spans) = 1 AND cardinality(spans) > 0 AND array_position(spans, NULL) IS NULL AND NOT ('empty'::numrange = ANY(spans)))),
	CHECK ((embedding IS NULL) = (embedding_config IS NULL)),
	FOREIGN KEY(okei) REFERENCES {catalogue_schema}.okei (code) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(embedding_config) REFERENCES {catalogue_schema}.embedding_configs (fingerprint)
);

CREATE INDEX ktru_position_embedding_hnsw ON {catalogue_schema}.ktru_position USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX ktru_position_okpd2 ON {catalogue_schema}.ktru_position (okpd2);

CREATE INDEX ktru_position_parent_code ON {catalogue_schema}.ktru_position (parent_code);

CREATE INDEX ktru_position_trgm ON {catalogue_schema}.ktru_position USING gin ({catalogue_schema}.norm(name) public.gin_trgm_ops);

CREATE INDEX kpgz_characteristic_kpgz_code ON {catalogue_schema}.kpgz_characteristic (import_sha256, kpgz_code);

CREATE INDEX kpgz_characteristic_name ON {catalogue_schema}.kpgz_characteristic (name);

CREATE INDEX ktru_characteristic_embedding_hnsw ON {catalogue_schema}.ktru_characteristic USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX ktru_characteristic_trgm ON {catalogue_schema}.ktru_characteristic USING gin ({catalogue_schema}.norm(name) public.gin_trgm_ops);

CREATE INDEX ktru_value_characteristic ON {catalogue_schema}.ktru_value (import_sha256, position_code, characteristic_code);

CREATE INDEX ktru_value_embedding_hnsw ON {catalogue_schema}.ktru_value USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX ktru_value_trgm ON {catalogue_schema}.ktru_value USING gin ({catalogue_schema}.norm(text) public.gin_trgm_ops);

CREATE VIEW {catalogue_schema}.ktru_domain AS
SELECT * FROM (
    SELECT p.*, CASE
        WHEN okpd2 LIKE '31.%'                     THEN 'Мебель'
        WHEN okpd2 ~ '^(14\.|15\.[12])'            THEN 'Одежда'
        WHEN okpd2 ~ '^(25\.7|28\.24|26\.51|27\.90)' THEN 'Инструменты'
    END AS domain
    FROM {catalogue_schema}.ktru_position p
) p WHERE domain IS NOT NULL;

COMMENT ON COLUMN {catalogue_schema}.ktru_position.parent_version IS 'XML parent version, retained as provenance; not a foreign key to the latest parent.';
COMMENT ON COLUMN {catalogue_schema}.ktru_value.ordinal IS 'Zero-based XML values/value order within a characteristic; repeated valueCode is retained.';
COMMENT ON COLUMN {catalogue_schema}.ktru_value.spans IS 'All points/ranges in one XML value; malformed groups are NULL with original XML in issue.';

ALTER TABLE analysis_runs ADD COLUMN catalogue_import_sha256 text
    REFERENCES {catalogue_schema}.catalogue_imports(sha256);
