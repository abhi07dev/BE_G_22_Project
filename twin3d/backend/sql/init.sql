CREATE TABLE IF NOT EXISTS positions (
  ts timestamptz NOT NULL, cam text NOT NULL, gid bigint NOT NULL,
  x real NOT NULL, y real NOT NULL, conf real
) PARTITION BY RANGE (ts);
CREATE TABLE IF NOT EXISTS positions_default PARTITION OF positions DEFAULT;
CREATE INDEX IF NOT EXISTS positions_ts_gid ON positions (ts, gid);
CREATE TABLE IF NOT EXISTS alerts (
  id bigserial PRIMARY KEY, ts timestamptz NOT NULL, type text NOT NULL,
  zone text, gid bigint, severity text, status text DEFAULT 'open', payload jsonb
);
CREATE TABLE IF NOT EXISTS users (
  id serial PRIMARY KEY, email text UNIQUE NOT NULL, password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'viewer'
);
