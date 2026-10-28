-- Followers or Facts Studio database.
-- Research tables keep truth-vlog's IDs (P-, O-, X-, A-, C-, S-) unchanged.
-- Production tables hang off one project_id per episode.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- ---------------------------------------------------------------- entities
CREATE TABLE IF NOT EXISTS person (
    person_id TEXT PRIMARY KEY CHECK (person_id LIKE 'P-%'),
    name TEXT NOT NULL, aka TEXT, role_types TEXT, orgs_text TEXT,
    first_kf_ep TEXT, first_seen_year TEXT, motive_notes TEXT, status TEXT,
    wiki_or_bio_url TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS organization (
    org_id TEXT PRIMARY KEY CHECK (org_id LIKE 'O-%'),
    name TEXT NOT NULL, type TEXT, founded TEXT, country TEXT, role TEXT,
    tactics TEXT, funding_notes TEXT, first_kf_ep TEXT, status TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS country (
    country_id TEXT PRIMARY KEY CHECK (country_id LIKE 'X-%'),
    name TEXT NOT NULL, influence_type TEXT, documented_vectors TEXT,
    key_cases TEXT, notes TEXT
);
-- When two IDs turned out to be the same entity, the old one points here.
CREATE TABLE IF NOT EXISTS entity_alias (
    alias_id TEXT PRIMARY KEY, canonical_id TEXT NOT NULL, reason TEXT
);

-- ---------------------------------------------------------------- stories
CREATE TABLE IF NOT EXISTS arc (
    arc_id TEXT PRIMARY KEY CHECK (arc_id LIKE 'A-%'),
    title TEXT NOT NULL, first_known_origin TEXT,
    status TEXT CHECK (status IN ('active','backlog','ongoing','planned','produced')),
    kf_eps_text TEXT, legacy_video_ids TEXT, harm_documented TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS claim (
    claim_id TEXT PRIMARY KEY CHECK (claim_id LIKE 'C-%'),
    short_title TEXT NOT NULL, claim_summary TEXT, first_known_year TEXT,
    peak_years TEXT, kf_eps_text TEXT,
    arc_id TEXT REFERENCES arc(arc_id),
    falsity_status TEXT CHECK (falsity_status IN
        ('false','misleading','contested','partially_true_wrapped','unverified')),
    harm_summary TEXT, who_benefited TEXT, society_effect TEXT,
    legacy_video_id TEXT,
    status TEXT CHECK (status IN ('seed','researched','needs_primary','video_ready'))
);
CREATE INDEX IF NOT EXISTS claim_arc ON claim(arc_id);
CREATE TABLE IF NOT EXISTS claim_entity (
    claim_id TEXT NOT NULL REFERENCES claim(claim_id),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person','org','country')),
    entity_id TEXT NOT NULL, link_role TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (claim_id, entity_type, entity_id, link_role)
);

-- ---------------------------------------------------------------- evidence
CREATE TABLE IF NOT EXISTS source (
    source_id TEXT PRIMARY KEY CHECK (source_id LIKE 'S-%'),
    title TEXT NOT NULL, publisher TEXT, date TEXT, url TEXT,
    source_type TEXT CHECK (source_type IN ('court','wire','gov','journalism',
        'archive_audio','academic','museum','kf_index','other')),
    reliability TEXT, notes TEXT,
    is_primary INTEGER GENERATED ALWAYS AS (source_type IN
        ('court','wire','gov','journalism','archive_audio','academic','museum')) VIRTUAL,
    -- filled in by "Fetch sources": a saved copy, its text, and when we looked
    local_copy_path TEXT, text_path TEXT, accessed_at TEXT,
    http_status INTEGER, content_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS claim_source (
    claim_id TEXT NOT NULL REFERENCES claim(claim_id),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    supports_field TEXT NOT NULL DEFAULT '', notes TEXT,
    PRIMARY KEY (claim_id, source_id, supports_field)
);
-- A sentence copied word for word from a saved source. Scripts may only quote these.
CREATE TABLE IF NOT EXISTS source_excerpt (
    excerpt_id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(source_id),
    claim_id TEXT REFERENCES claim(claim_id),
    text TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT, added_at TEXT
);
CREATE TABLE IF NOT EXISTS relationship (
    rel_id INTEGER PRIMARY KEY,
    from_type TEXT, from_id TEXT, to_type TEXT, to_id TEXT, relation TEXT,
    start_year TEXT, end_year TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS relationship_source (
    rel_id INTEGER NOT NULL REFERENCES relationship(rel_id),
    source_id TEXT NOT NULL,
    PRIMARY KEY (rel_id, source_id)
);

-- ---------------------------------------------------------------- Knowledge Fight index (a map, never evidence)
CREATE TABLE IF NOT EXISTS kf_episode (
    kf_ep TEXT PRIMARY KEY, kf_ep_num INTEGER, year INTEGER, air_date TEXT,
    title TEXT, topics TEXT, priority TEXT, deep_pass TEXT, notes TEXT,
    careful INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kf_episode_link (
    kf_ep TEXT NOT NULL REFERENCES kf_episode(kf_ep),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('claim','person','org','country')),
    entity_id TEXT NOT NULL,
    PRIMARY KEY (kf_ep, entity_type, entity_id)
);
CREATE TABLE IF NOT EXISTS research_note (
    note_id INTEGER PRIMARY KEY, year INTEGER, path TEXT, body_md TEXT
);

-- ---------------------------------------------------------------- careful topics
-- Rules the pipeline enforces. courts_only: only court/gov sources on screen.
-- no_names: never name private individuals. no_footage: no imagery of the event.
CREATE TABLE IF NOT EXISTS content_restriction (
    subject_type TEXT NOT NULL CHECK (subject_type IN ('claim','arc','person')),
    subject_id TEXT NOT NULL,
    rule TEXT NOT NULL CHECK (rule IN ('courts_only','no_names','no_footage',
        'mechanism_only','no_person_imagery')),
    note TEXT,
    PRIMARY KEY (subject_type, subject_id, rule)
);

-- ---------------------------------------------------------------- production
CREATE TABLE IF NOT EXISTS project (
    project_id TEXT PRIMARY KEY,          -- e.g. S01E01
    title TEXT NOT NULL,
    arc_id TEXT REFERENCES arc(arc_id),
    legacy_video_id TEXT,
    folder TEXT NOT NULL,                 -- relative to the episodes folder
    created_at TEXT NOT NULL,
    youtube_id TEXT
);
CREATE TABLE IF NOT EXISTS project_claim (
    project_id TEXT NOT NULL REFERENCES project(project_id),
    claim_id TEXT NOT NULL REFERENCES claim(claim_id),
    order_no INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, claim_id)
);
-- Append-only history of every stage result and every approval decision.
CREATE TABLE IF NOT EXISTS stage_event (
    event_id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(project_id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','awaiting_approval',
        'approved','rejected','failed','cancelled','interrupted','reset')),
    note TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stage_event_project ON stage_event(project_id, stage, event_id);

CREATE TABLE IF NOT EXISTS job (
    job_id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(project_id),
    stage TEXT NOT NULL,
    gpu INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed',
        'cancelled','interrupted')),
    options_json TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    pid INTEGER, heartbeat_at TEXT, progress TEXT,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
    error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
);
-- Only one job can run at a time: a 12 GB card cannot hold two models.
CREATE UNIQUE INDEX IF NOT EXISTS one_running_job ON job(status) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS queue_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    paused INTEGER NOT NULL DEFAULT 0,
    reason TEXT
);
INSERT OR IGNORE INTO queue_control(id, paused) VALUES (1, 0);

-- Pages the research agents downloaded (so nothing is fetched twice) and API use per day.
CREATE TABLE IF NOT EXISTS web_cache (
    url TEXT PRIMARY KEY, fetched_at TEXT, status INTEGER, content_type TEXT,
    path TEXT, text_path TEXT, final_url TEXT, via TEXT
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT NOT NULL, provider TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);

CREATE TABLE IF NOT EXISTS legacy_video_tracker (row_json TEXT NOT NULL);

-- ---------------------------------------------------------------- readiness, computed from data
CREATE VIEW IF NOT EXISTS claim_readiness AS
SELECT c.claim_id, c.arc_id, c.short_title, c.falsity_status, c.status,
       COUNT(DISTINCT CASE WHEN s.is_primary = 1 THEN s.source_id END) AS primary_sources,
       COUNT(DISTINCT CASE WHEN s.source_type = 'kf_index' THEN s.source_id END) AS kf_sources,
       EXISTS (SELECT 1 FROM content_restriction r
               WHERE (r.subject_type = 'claim' AND r.subject_id = c.claim_id)
                  OR (r.subject_type = 'arc' AND r.subject_id = c.arc_id)) AS careful
FROM claim c
LEFT JOIN claim_source cs ON cs.claim_id = c.claim_id
LEFT JOIN source s ON s.source_id = cs.source_id
GROUP BY c.claim_id;

CREATE VIEW IF NOT EXISTS arc_strength AS
SELECT a.arc_id, a.title, a.status,
       COUNT(r.claim_id) AS claims,
       SUM(CASE WHEN r.primary_sources > 0 THEN 1 ELSE 0 END) AS sourced_claims,
       SUM(CASE WHEN r.primary_sources >= 3 THEN 1 ELSE 0 END) AS well_sourced_claims,
       MAX(r.careful) AS careful
FROM arc a LEFT JOIN claim_readiness r ON r.arc_id = a.arc_id
GROUP BY a.arc_id;

-- Caricature designs: how a public figure who sold a lie is drawn as a cartoon. Written once,
-- approved by Dave, reused in every episode (so they look the same each time).
CREATE TABLE IF NOT EXISTS caricature (
    person_id TEXT PRIMARY KEY,
    design TEXT NOT NULL,           -- hair, glasses, build, clothes, props; never the person's name
    approved INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    notes TEXT,
    design_json TEXT,               -- the structured design the text was written from
    references_json TEXT,           -- the photos looked at (audit trail only)
    search_hint TEXT                -- who this is, for the photo search ("InfoWars conspiracy radio host")
);
