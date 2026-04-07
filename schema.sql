-- The Director: minimal schema — credentials and sync log only.
-- No user table (single-user system).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- OAuth tokens, API keys, sync cursors
CREATE TABLE IF NOT EXISTS credentials (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider    TEXT NOT NULL UNIQUE,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Track sync runs
CREATE TABLE IF NOT EXISTS sync_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider    TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'running',
    items_synced INTEGER DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_log_provider
    ON sync_log (provider, started_at DESC);
