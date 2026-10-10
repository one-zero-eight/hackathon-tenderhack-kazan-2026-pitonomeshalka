CREATE TABLE catalog_snapshots (
    sha256 text PRIMARY KEY,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog_sources (
    key text PRIMARY KEY,
    snapshot_sha256 text NOT NULL REFERENCES catalog_snapshots(sha256)
);
CREATE TABLE catalog_positions (
    snapshot_sha256 text NOT NULL REFERENCES catalog_snapshots(sha256) ON DELETE CASCADE,
    key text NOT NULL,
    code text NOT NULL,
    version text NOT NULL,
    name text NOT NULL,
    domains text[] NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_sha256, key)
);
CREATE INDEX catalog_positions_name ON catalog_positions(name);
CREATE TABLE catalog_facts (
    snapshot_sha256 text NOT NULL REFERENCES catalog_snapshots(sha256) ON DELETE CASCADE,
    id text NOT NULL,
    name text NOT NULL,
    value text NOT NULL,
    unit_code text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_sha256, id)
);
CREATE TABLE embedding_indexes (
    fingerprint text PRIMARY KEY,
    model text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions > 0),
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog_embeddings (
    fingerprint text NOT NULL REFERENCES embedding_indexes(fingerprint) ON DELETE CASCADE,
    name text NOT NULL,
    ordinal integer NOT NULL,
    embedding public.vector NOT NULL,
    PRIMARY KEY (fingerprint, name),
    UNIQUE (fingerprint, ordinal)
);
CREATE TABLE analysis_runs (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    catalog_sha256 text REFERENCES catalog_snapshots(sha256),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'interrupted')),
    request jsonb NOT NULL,
    plan jsonb,
    planned_requests integer,
    planned_questions integer,
    error text,
    result jsonb,
    analysis jsonb
);
CREATE INDEX analysis_runs_created_at ON analysis_runs(created_at DESC);
CREATE TABLE run_artifacts (
    run_id text NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    name text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (run_id, name)
);
CREATE TABLE model_calls (
    run_id text NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    requested_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    request_id text NOT NULL,
    experiment text NOT NULL,
    method text NOT NULL,
    url text NOT NULL,
    request json NOT NULL,
    outgoing json NOT NULL,
    response json,
    record json,
    error text,
    elapsed_seconds double precision,
    PRIMARY KEY (run_id, ordinal)
);
CREATE TABLE connection_checks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    checked_at timestamptz NOT NULL,
    service text NOT NULL,
    url text NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (checked_at, service, url)
);
CREATE TABLE embedding_calls (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    run_id text REFERENCES analysis_runs(id) ON DELETE SET NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    request json NOT NULL,
    model text NOT NULL,
    url text NOT NULL,
    dimensions integer,
    elapsed_seconds double precision,
    error text
);
