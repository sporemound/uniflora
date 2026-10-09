-- Website identities share the existing session store while Discord sessions
-- remain valid during the transport migration.
ALTER TABLE activity_sessions ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'discord';
ALTER TABLE activity_sessions ADD COLUMN email_hash TEXT;

CREATE INDEX IF NOT EXISTS activity_sessions_email_hash
ON activity_sessions (email_hash, expires_at);

CREATE TABLE IF NOT EXISTS web_magic_links (
    token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64),
    email TEXT NOT NULL,
    email_hash TEXT NOT NULL CHECK (length(email_hash) = 64),
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at INTEGER,
    CHECK (expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS web_magic_links_expires
ON web_magic_links (expires_at);

-- The conditional upsert in the Worker enforces one issuance per address per
-- minute across isolates and regions. The address is never stored in this table.
CREATE TABLE IF NOT EXISTS web_magic_link_cooldowns (
    email_hash TEXT PRIMARY KEY CHECK (length(email_hash) = 64),
    next_allowed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS web_magic_link_cooldowns_expiry
ON web_magic_link_cooldowns (next_allowed_at);
