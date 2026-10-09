CREATE TABLE IF NOT EXISTS activity_difficulty_preferences (
  environment TEXT NOT NULL CHECK (environment IN ('test', 'live')),
  discord_user_id TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('guided', 'standard', 'expert')),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (environment, discord_user_id)
);
