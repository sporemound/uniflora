PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS current_public_state (
    environment TEXT PRIMARY KEY CHECK (environment IN ('live', 'test')),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state_head_hash TEXT NOT NULL,
    previous_state_head_hash TEXT,
    snapshot_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public_state_revisions (
    environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state_head_hash TEXT NOT NULL,
    previous_revision INTEGER,
    previous_state_head_hash TEXT,
    snapshot_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY (environment, revision),
    UNIQUE (environment, state_head_hash),
    UNIQUE (environment, revision, state_head_hash),
    CHECK (
        (
            revision = 1
            AND previous_revision IS NULL
            AND previous_state_head_hash IS NULL
        )
        OR
        (
            revision > 1
            AND previous_revision = revision - 1
            AND previous_state_head_hash IS NOT NULL
        )
    ),
    FOREIGN KEY (
        environment,
        previous_revision,
        previous_state_head_hash
    ) REFERENCES public_state_revisions (
        environment,
        revision,
        state_head_hash
    )
);

CREATE TABLE IF NOT EXISTS hypha_request_nonces (
    nonce TEXT PRIMARY KEY,
    request_path TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    accepted_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS hypha_request_nonces_expires
ON hypha_request_nonces (expires_at);

CREATE TABLE IF NOT EXISTS published_artifact_files (
    environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
    artifact_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    content_sha256 TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (environment, artifact_id, filename)
);

CREATE INDEX IF NOT EXISTS published_artifact_files_artifact
ON published_artifact_files (environment, artifact_id);

CREATE TABLE IF NOT EXISTS public_publications (
    environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
    publication_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    state_head_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    public_summary TEXT NOT NULL,
    limitation TEXT NOT NULL,
    primary_filename TEXT NOT NULL,
    manifest_filename TEXT,
    publication_json TEXT NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY (environment, publication_id)
);

CREATE INDEX IF NOT EXISTS public_publications_artifact
ON public_publications (environment, artifact_id);

CREATE TABLE IF NOT EXISTS activity_sessions (
    session_hash TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS activity_sessions_expires
ON activity_sessions (expires_at);
