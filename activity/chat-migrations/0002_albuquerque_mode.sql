-- Keep the presentation choice attached to the submitted question. Existing
-- queued requests retain ordinary replies after this additive migration.
ALTER TABLE hypha_chat_requests
ADD COLUMN albuquerque_mode INTEGER NOT NULL DEFAULT 0
CHECK (albuquerque_mode IN (0, 1));
