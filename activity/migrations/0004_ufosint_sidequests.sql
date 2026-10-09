PRAGMA foreign_keys = ON;

-- Durable, report-bound investigations. The normalized report snapshot is kept
-- on the root row and is deliberately immutable after insertion.
CREATE TABLE IF NOT EXISTS ufosint_sidequests (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  template_version TEXT NOT NULL CHECK (length(template_version) BETWEEN 1 AND 128),
  report_source_key TEXT NOT NULL CHECK (report_source_key = 'ufosint'),
  report_id TEXT NOT NULL,
  report_snapshot_json TEXT NOT NULL CHECK (
    length(report_snapshot_json) BETWEEN 2 AND 256000
    AND json_valid(report_snapshot_json)
  ),
  report_snapshot_sha256 TEXT NOT NULL CHECK (
    length(report_snapshot_sha256) = 64
    AND report_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 240),
  lifecycle TEXT NOT NULL CHECK (
    lifecycle IN ('open', 'collecting', 'review', 'concluded', 'archived')
  ),
  revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
  opened_by_participant_id TEXT NOT NULL,
  opened_by_display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  concluded_at TEXT,
  archived_at TEXT,
  PRIMARY KEY (environment, sidequest_id),
  UNIQUE (environment, report_source_key, report_id),
  CHECK (
    (lifecycle IN ('open', 'collecting', 'review') AND concluded_at IS NULL AND archived_at IS NULL)
    OR (lifecycle = 'concluded' AND concluded_at IS NOT NULL AND archived_at IS NULL)
    OR (lifecycle = 'archived' AND archived_at IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequests_lifecycle
  ON ufosint_sidequests (environment, lifecycle, updated_at DESC, sidequest_id);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequests_report
  ON ufosint_sidequests (environment, report_source_key, report_id);

-- One append-only event per aggregate revision. operation_id plus the request
-- digest supplies durable idempotency; the trigger below supplies optimistic
-- concurrency without relying on a read followed by an unguarded write.
CREATE TABLE IF NOT EXISTS ufosint_sidequest_events (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  operation_id TEXT NOT NULL,
  operation_type TEXT NOT NULL CHECK (
    operation_type IN (
      'sidequest_created',
      'lifecycle_updated',
      'task_updated',
      'finding_added',
      'review_added',
      'artifact_attached'
    )
  ),
  request_sha256 TEXT NOT NULL CHECK (
    length(request_sha256) = 64
    AND request_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  actor_participant_id TEXT NOT NULL,
  actor_display_name TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (
    length(payload_json) BETWEEN 2 AND 128000
    AND json_valid(payload_json)
  ),
  created_at TEXT NOT NULL,
  PRIMARY KEY (environment, sidequest_id, revision),
  UNIQUE (environment, sidequest_id, operation_id),
  FOREIGN KEY (environment, sidequest_id)
    REFERENCES ufosint_sidequests (environment, sidequest_id)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_events_operation
  ON ufosint_sidequest_events (environment, sidequest_id, operation_id);

CREATE TABLE IF NOT EXISTS ufosint_sidequest_tasks (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  task_kind TEXT NOT NULL CHECK (
    task_kind IN (
      'provenance',
      'witness',
      'geographic',
      'temporal',
      'meteorological',
      'aviation',
      'astronomical',
      'sensor',
      'alternative_hypothesis',
      'synthesis',
      'peer_review'
    )
  ),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 240),
  instructions TEXT NOT NULL CHECK (length(instructions) BETWEEN 1 AND 4000),
  required INTEGER NOT NULL CHECK (required IN (0, 1)),
  status TEXT NOT NULL CHECK (
    status IN ('pending', 'in_progress', 'completed', 'waived', 'unavailable')
  ),
  assigned_participant_id TEXT,
  assigned_display_name TEXT,
  completion_note TEXT CHECK (
    completion_note IS NULL OR length(completion_note) BETWEEN 1 AND 2000
  ),
  completed_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (environment, sidequest_id, task_id),
  UNIQUE (environment, sidequest_id, ordinal),
  FOREIGN KEY (environment, sidequest_id)
    REFERENCES ufosint_sidequests (environment, sidequest_id)
    ON DELETE RESTRICT,
  CHECK (
    (status IN ('pending', 'in_progress') AND completed_at IS NULL)
    OR (status IN ('completed', 'waived', 'unavailable') AND completed_at IS NOT NULL)
  ),
  CHECK (
    (assigned_participant_id IS NULL AND assigned_display_name IS NULL)
    OR (assigned_participant_id IS NOT NULL AND assigned_display_name IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_tasks_status
  ON ufosint_sidequest_tasks (environment, sidequest_id, status, ordinal);

-- Findings are immutable exact revisions. A later revision points at its exact
-- predecessor, while reviews remain attached to the revision they assessed.
CREATE TABLE IF NOT EXISTS ufosint_sidequest_finding_revisions (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  finding_id TEXT NOT NULL,
  finding_revision INTEGER NOT NULL CHECK (finding_revision >= 1),
  previous_revision INTEGER,
  finding_kind TEXT NOT NULL CHECK (
    finding_kind IN (
      'observation',
      'provenance',
      'correlation',
      'ordinary_explanation',
      'limitation',
      'conclusion'
    )
  ),
  statement TEXT NOT NULL CHECK (length(statement) BETWEEN 1 AND 2000),
  confidence TEXT NOT NULL CHECK (
    confidence IN ('unknown', 'low', 'moderate', 'high')
  ),
  finding_json TEXT NOT NULL CHECK (
    length(finding_json) BETWEEN 2 AND 256000
    AND json_valid(finding_json)
  ),
  author_participant_id TEXT NOT NULL,
  author_display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (environment, sidequest_id, finding_id, finding_revision),
  FOREIGN KEY (environment, sidequest_id)
    REFERENCES ufosint_sidequests (environment, sidequest_id)
    ON DELETE RESTRICT,
  FOREIGN KEY (environment, sidequest_id, finding_id, previous_revision)
    REFERENCES ufosint_sidequest_finding_revisions (
      environment,
      sidequest_id,
      finding_id,
      finding_revision
    )
    ON DELETE RESTRICT,
  CHECK (
    (finding_revision = 1 AND previous_revision IS NULL)
    OR (finding_revision > 1 AND previous_revision = finding_revision - 1)
  )
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_findings_latest
  ON ufosint_sidequest_finding_revisions (
    environment,
    sidequest_id,
    finding_id,
    finding_revision DESC
  );

CREATE TABLE IF NOT EXISTS ufosint_sidequest_reviews (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  review_id TEXT NOT NULL,
  finding_id TEXT NOT NULL,
  finding_revision INTEGER NOT NULL CHECK (finding_revision >= 1),
  reviewer_participant_id TEXT NOT NULL,
  reviewer_display_name TEXT NOT NULL,
  disposition TEXT NOT NULL CHECK (
    disposition IN ('endorse', 'challenge', 'request_revision')
  ),
  rationale TEXT NOT NULL CHECK (length(rationale) BETWEEN 1 AND 2000),
  rubric_json TEXT CHECK (
    rubric_json IS NULL
    OR (length(rubric_json) BETWEEN 2 AND 4000 AND json_valid(rubric_json))
  ),
  created_at TEXT NOT NULL,
  PRIMARY KEY (environment, sidequest_id, review_id),
  UNIQUE (
    environment,
    sidequest_id,
    finding_id,
    finding_revision,
    reviewer_participant_id
  ),
  FOREIGN KEY (environment, sidequest_id, finding_id, finding_revision)
    REFERENCES ufosint_sidequest_finding_revisions (
      environment,
      sidequest_id,
      finding_id,
      finding_revision
    )
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_reviews_finding
  ON ufosint_sidequest_reviews (
    environment,
    sidequest_id,
    finding_id,
    finding_revision,
    created_at
  );

-- Every artifact retains its exact, bounded canonical Base64 bytes alongside
-- an immutable, hash-addressed metadata envelope and the explicit provenance
-- edges needed to reproduce or audit a result.
CREATE TABLE IF NOT EXISTS ufosint_sidequest_artifacts (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  artifact_kind TEXT NOT NULL CHECK (
    artifact_kind IN (
      'source_capture',
      'metadata_extract',
      'weather_context',
      'flight_context',
      'satellite_context',
      'astronomical_context',
      'geospatial_analysis',
      'dynamical_analysis',
      'timeline',
      'comparison_matrix',
      'narrative_note'
    )
  ),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 240),
  media_type TEXT NOT NULL CHECK (length(media_type) BETWEEN 1 AND 120),
  content_sha256 TEXT NOT NULL CHECK (
    length(content_sha256) = 64
    AND content_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  byte_length INTEGER NOT NULL CHECK (byte_length BETWEEN 0 AND 256000),
  content_base64 TEXT NOT NULL CHECK (
    length(content_base64) <= 341336
    AND length(content_base64) = 4 * ((byte_length + 2) / 3)
    AND content_base64 NOT GLOB '*[^A-Za-z0-9+/=]*'
  ),
  artifact_uri TEXT,
  artifact_json TEXT NOT NULL CHECK (
    length(artifact_json) BETWEEN 2 AND 256000
    AND json_valid(artifact_json)
  ),
  created_by_participant_id TEXT NOT NULL,
  created_by_display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (environment, sidequest_id, artifact_id),
  FOREIGN KEY (environment, sidequest_id)
    REFERENCES ufosint_sidequests (environment, sidequest_id)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_artifacts_hash
  ON ufosint_sidequest_artifacts (content_sha256);

CREATE TABLE IF NOT EXISTS ufosint_sidequest_artifact_provenance (
  environment TEXT NOT NULL CHECK (environment IN ('live', 'test')),
  sidequest_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  provenance_id TEXT NOT NULL,
  parent_type TEXT NOT NULL CHECK (
    parent_type IN ('report_snapshot', 'artifact', 'external_source')
  ),
  parent_reference TEXT NOT NULL,
  parent_content_sha256 TEXT CHECK (
    parent_content_sha256 IS NULL
    OR (
      length(parent_content_sha256) = 64
      AND parent_content_sha256 NOT GLOB '*[^0-9a-f]*'
    )
  ),
  relation TEXT NOT NULL CHECK (
    relation IN (
      'derived_from',
      'summarizes',
      'visualizes',
      'validates',
      'challenges',
      'contextualizes'
    )
  ),
  description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 1000),
  retrieved_at TEXT,
  PRIMARY KEY (environment, sidequest_id, artifact_id, provenance_id),
  FOREIGN KEY (environment, sidequest_id, artifact_id)
    REFERENCES ufosint_sidequest_artifacts (
      environment,
      sidequest_id,
      artifact_id
    )
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ufosint_sidequest_provenance_parent
  ON ufosint_sidequest_artifact_provenance (
    environment,
    sidequest_id,
    parent_type,
    parent_reference
  );

-- The plan may be populated only while the root is at revision zero. Once the
-- creation event freezes the aggregate, task identity and instructions cannot
-- drift underneath the immutable template version.
CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_task_count
BEFORE INSERT ON ufosint_sidequest_tasks
WHEN (
  SELECT COUNT(*)
  FROM ufosint_sidequest_tasks
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) >= 24
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest task limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_tasks_no_late_insert
BEFORE INSERT ON ufosint_sidequest_tasks
WHEN (
  SELECT revision
  FROM ufosint_sidequests
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) > 0
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest task definitions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_task_definitions_no_update
BEFORE UPDATE OF task_id, ordinal, task_kind, title, instructions, required
ON ufosint_sidequest_tasks
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest task definitions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_tasks_no_delete
BEFORE DELETE ON ufosint_sidequest_tasks
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest task definitions are immutable');
END;

-- Aggregate ceilings keep append-only research records bounded enough to load
-- as one authenticated snapshot. Application checks improve errors; these
-- triggers are the race-safe storage authority.
CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_finding_count
BEFORE INSERT ON ufosint_sidequest_finding_revisions
WHEN (
  SELECT COUNT(*)
  FROM ufosint_sidequest_finding_revisions
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) >= 128
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT finding revision limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_finding_json_total
BEFORE INSERT ON ufosint_sidequest_finding_revisions
WHEN COALESCE((
  SELECT SUM(length(finding_json))
  FROM ufosint_sidequest_finding_revisions
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
), 0) + length(NEW.finding_json) > 300000
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT finding JSON aggregate limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_review_count
BEFORE INSERT ON ufosint_sidequest_reviews
WHEN (
  SELECT COUNT(*)
  FROM ufosint_sidequest_reviews
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) >= 128
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT review limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_review_json_total
BEFORE INSERT ON ufosint_sidequest_reviews
WHEN COALESCE((
  SELECT SUM(length(rationale) + COALESCE(length(rubric_json), 0))
  FROM ufosint_sidequest_reviews
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
), 0) + length(NEW.rationale) + COALESCE(length(NEW.rubric_json), 0) > 150000
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT review JSON aggregate limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_artifact_count
BEFORE INSERT ON ufosint_sidequest_artifacts
WHEN (
  SELECT COUNT(*)
  FROM ufosint_sidequest_artifacts
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) >= 128
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifact limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_artifact_json_total
BEFORE INSERT ON ufosint_sidequest_artifacts
WHEN COALESCE((
  SELECT SUM(length(artifact_json))
  FROM ufosint_sidequest_artifacts
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
), 0) + length(NEW.artifact_json) > 300000
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifact JSON aggregate limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_artifact_content_total
BEFORE INSERT ON ufosint_sidequest_artifacts
WHEN COALESCE((
  SELECT SUM(byte_length)
  FROM ufosint_sidequest_artifacts
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
), 0) + NEW.byte_length > 8000000
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifact content aggregate limit exceeded');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_report_immutable
BEFORE UPDATE OF
  template_version,
  report_source_key,
  report_id,
  report_snapshot_json,
  report_snapshot_sha256
ON ufosint_sidequests
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT report snapshot is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_revision_step
BEFORE UPDATE OF revision ON ufosint_sidequests
WHEN NEW.revision <> OLD.revision + 1
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest revision must increase by one');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_event_revision
BEFORE INSERT ON ufosint_sidequest_events
WHEN (
  SELECT revision
  FROM ufosint_sidequests
  WHERE environment = NEW.environment AND sidequest_id = NEW.sidequest_id
) <> NEW.revision - 1
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest revision conflict');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_events_no_update
BEFORE UPDATE ON ufosint_sidequest_events
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_events_no_delete
BEFORE DELETE ON ufosint_sidequest_events
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT sidequest events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_findings_no_update
BEFORE UPDATE ON ufosint_sidequest_finding_revisions
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT finding revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_findings_no_delete
BEFORE DELETE ON ufosint_sidequest_finding_revisions
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT finding revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_reviews_no_update
BEFORE UPDATE ON ufosint_sidequest_reviews
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT reviews are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_reviews_no_delete
BEFORE DELETE ON ufosint_sidequest_reviews
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT reviews are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_artifacts_no_update
BEFORE UPDATE ON ufosint_sidequest_artifacts
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_artifacts_no_delete
BEFORE DELETE ON ufosint_sidequest_artifacts
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_provenance_no_update
BEFORE UPDATE ON ufosint_sidequest_artifact_provenance
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifact provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_ufosint_sidequest_provenance_no_delete
BEFORE DELETE ON ufosint_sidequest_artifact_provenance
BEGIN
  SELECT RAISE(ABORT, 'UFOSINT artifact provenance is immutable');
END;

PRAGMA optimize;
