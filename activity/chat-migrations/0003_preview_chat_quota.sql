-- Gemini spend is bounded per verified email participant, across Worker isolates.
CREATE TABLE IF NOT EXISTS preview_chat_quota (
    participant_id TEXT NOT NULL,
    window_kind TEXT NOT NULL CHECK (window_kind IN ('minute', 'day')),
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 1),
    PRIMARY KEY (participant_id, window_kind, window_start)
);

CREATE INDEX IF NOT EXISTS preview_chat_quota_expiry
ON preview_chat_quota (window_kind, window_start);
