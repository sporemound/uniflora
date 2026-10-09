ALTER TABLE activity_sessions ADD COLUMN discord_user_id TEXT;
ALTER TABLE activity_sessions ADD COLUMN instance_id TEXT;
ALTER TABLE activity_sessions ADD COLUMN guild_id TEXT;
ALTER TABLE activity_sessions ADD COLUMN channel_id TEXT;

CREATE INDEX IF NOT EXISTS activity_sessions_instance
ON activity_sessions (instance_id, expires_at);
