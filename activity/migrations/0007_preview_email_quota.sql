-- Preview-only limits bound outbound email use without retaining requester IPs.
CREATE TABLE IF NOT EXISTS preview_magic_link_quota (
    subject_key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 1),
    PRIMARY KEY (subject_key, window_start)
);

CREATE INDEX IF NOT EXISTS preview_magic_link_quota_expiry
ON preview_magic_link_quota (window_start);
