-- moswalk // — Flywheel archive schema for Supabase
--
-- Run this once in the Supabase SQL editor (Dashboard → SQL Editor → New query).
--
-- Security:
--   - Enable Row Level Security on both tables
--   - No public access — service role key only (server-side Python process)
--   - SUPABASE_KEY in env must be the service role key, never the anon key
--   - No client PII stored here: BBL + examiner_id only
--   - NY SHIELD Act: this table holds public-record property data only
--
-- After running this SQL, set in your Mac environment:
--   export SUPABASE_URL="https://your-project.supabase.co"
--   export SUPABASE_KEY="your-service-role-key"   # NOT the anon key
--   export FLYWHEEL_BACKEND="both"                 # sqlite + supabase

-- ── jobs ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS moswalk_jobs (
    job_id               TEXT PRIMARY KEY,
    engagement_id        TEXT,
    bbl                  TEXT,
    borough              TEXT,
    filing_type          TEXT,
    filing_mode          TEXT,
    examiner_id          TEXT,
    outcome              TEXT,
    confidence_score     DOUBLE PRECISION,
    pathway_type         TEXT,
    enforcement_context  TEXT,
    filing_date          TEXT,
    first_objection_date TEXT,
    approval_date        TEXT,
    created_at           DOUBLE PRECISION,
    updated_at           DOUBLE PRECISION,
    payload              JSONB          -- full JobRecord as JSON
);

CREATE INDEX IF NOT EXISTS idx_mj_bbl          ON moswalk_jobs(bbl);
CREATE INDEX IF NOT EXISTS idx_mj_examiner     ON moswalk_jobs(examiner_id);
CREATE INDEX IF NOT EXISTS idx_mj_filing_type  ON moswalk_jobs(filing_type);
CREATE INDEX IF NOT EXISTS idx_mj_borough_ft   ON moswalk_jobs(borough, filing_type);
CREATE INDEX IF NOT EXISTS idx_mj_updated      ON moswalk_jobs(updated_at DESC);

ALTER TABLE moswalk_jobs ENABLE ROW LEVEL SECURITY;
-- No public policy: only the service role key can read/write.

-- ── objections ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS moswalk_objections (
    id                 BIGSERIAL PRIMARY KEY,
    job_id             TEXT NOT NULL REFERENCES moswalk_jobs(job_id) ON DELETE CASCADE,
    bbl                TEXT,
    objection_code     TEXT,
    description        TEXT,
    resolution_method  TEXT,
    resolution_days    INTEGER,
    documentation_used JSONB          -- array of strings
);

CREATE INDEX IF NOT EXISTS idx_mo_objection_code ON moswalk_objections(objection_code);
CREATE INDEX IF NOT EXISTS idx_mo_job_id         ON moswalk_objections(job_id);

ALTER TABLE moswalk_objections ENABLE ROW LEVEL SECURITY;
