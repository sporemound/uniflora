PRAGMA foreign_keys = ON;

-- Queue rows contain private relay metadata and may be pruned after completion.
-- Shared messages and audio remain scoped to the authoritative v2 stream.
CREATE TABLE IF NOT EXISTS hypha_chat_requests (
    request_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    privacy_alias TEXT,
    environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
    stream_id TEXT NOT NULL CHECK (length(stream_id) BETWEEN 1 AND 128),
    message_text TEXT NOT NULL CHECK (length(message_text) BETWEEN 1 AND 4000),
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
    participant_message_id TEXT NOT NULL UNIQUE,
    hypha_message_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    claimed_at INTEGER,
    completed_at INTEGER,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS hypha_chat_requests_queue
ON hypha_chat_requests (environment, stream_id, status, created_at);

CREATE INDEX IF NOT EXISTS hypha_chat_requests_expires
ON hypha_chat_requests (expires_at);

CREATE TABLE IF NOT EXISTS hypha_chat_messages (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
    stream_id TEXT NOT NULL CHECK (length(stream_id) BETWEEN 1 AND 128),
    sender_type TEXT NOT NULL CHECK (sender_type IN ('participant', 'hypha')),
    participant_id TEXT,
    working_name TEXT,
    content_text TEXT NOT NULL CHECK (length(content_text) <= 4000),
    delivery_status TEXT NOT NULL CHECK (
        delivery_status IN ('pending', 'processing', 'complete', 'failed')
    ),
    audio_available INTEGER NOT NULL DEFAULT 0 CHECK (audio_available IN (0, 1)),
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    CHECK (
        (sender_type = 'participant' AND participant_id IS NOT NULL
            AND working_name IS NOT NULL AND delivery_status = 'complete')
        OR
        (sender_type = 'hypha' AND participant_id IS NULL AND working_name IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS hypha_chat_messages_scope
ON hypha_chat_messages (environment, stream_id, row_id);

CREATE INDEX IF NOT EXISTS hypha_chat_messages_request
ON hypha_chat_messages (request_id, sender_type);

-- D1 limits a BLOB/row to 2 MB. Worker validation caps OGG at 1.5 MB.
CREATE TABLE IF NOT EXISTS hypha_chat_audio (
    message_id TEXT PRIMARY KEY REFERENCES hypha_chat_messages(message_id) ON DELETE CASCADE,
    audio_bytes BLOB NOT NULL CHECK (length(audio_bytes) BETWEEN 1 AND 1500000),
    created_at INTEGER NOT NULL
);
