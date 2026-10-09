CREATE TABLE IF NOT EXISTS room_ticket_nonces (
  nonce TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  room_id TEXT NOT NULL,
  accepted_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_room_ticket_nonces_expires_at
  ON room_ticket_nonces (expires_at);
