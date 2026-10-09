import {
  normalizePublicActivitySnapshot,
  type PublicActivitySnapshot,
} from "../../src/shared/public-state";
import type { D1Database, D1PreparedStatement } from "./cloudflare";
import { HttpError } from "./errors";
import type { PublicationPayload } from "./validation";

export interface CurrentStateRow {
  environment: string;
  revision: number;
  state_head_hash: string;
  previous_state_head_hash: string | null;
  snapshot_json: string;
  payload_sha256: string;
  updated_at: string;
}

export interface ArtifactFileRow {
  environment: string;
  artifact_id: string;
  filename: string;
  object_key: string;
  content_type: string;
  byte_length: number;
  content_sha256: string;
  uploaded_at: string;
}

export interface LatestPublicationRow {
  publication_json: string;
}

export interface SessionRow {
  session_hash: string;
  participant_id: string;
  display_name: string;
  avatar_url: string | null;
  discord_user_id: string | null;
  instance_id: string | null;
  guild_id: string | null;
  channel_id: string | null;
  issued_at: number;
  expires_at: number;
  last_seen_at: number;
}

export function nonceInsert(
  db: D1Database,
  input: {
    nonce: string;
    requestPath: string;
    bodySha256: string;
    acceptedAt: number;
    expiresAt: number;
  },
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT INTO hypha_request_nonces (
        nonce, request_path, body_sha256, accepted_at, expires_at
      ) VALUES (?, ?, ?, ?, ?)`,
    )
    .bind(
      input.nonce,
      input.requestPath,
      input.bodySha256,
      input.acceptedAt,
      input.expiresAt,
    );
}

export async function cleanupExpiredRows(
  db: D1Database,
  nowSeconds: number,
): Promise<void> {
  await db.batch([
    db
      .prepare("DELETE FROM hypha_request_nonces WHERE expires_at < ?")
      .bind(nowSeconds),
    db
      .prepare("DELETE FROM activity_sessions WHERE expires_at < ?")
      .bind(nowSeconds),
    db
      .prepare("DELETE FROM room_ticket_nonces WHERE expires_at < ?")
      .bind(nowSeconds),
  ]);
}

export async function cleanupExpiredChatRows(
  db: D1Database,
  nowSeconds: number,
): Promise<void> {
  await db.batch([
    db.prepare(
      `UPDATE hypha_chat_messages
       SET delivery_status = 'failed',
           content_text = 'Hypha could not complete this response.',
           completed_at = ?
       WHERE sender_type = 'hypha' AND delivery_status IN ('pending', 'processing')
         AND request_id IN (
           SELECT request_id FROM hypha_chat_requests
           WHERE expires_at < ? AND status IN ('pending', 'processing')
         )`,
    ).bind(nowSeconds, nowSeconds),
    db.prepare("DELETE FROM hypha_chat_requests WHERE expires_at < ?")
      .bind(nowSeconds),
  ]);
}


export async function consumeRoomTicketNonce(
  db: D1Database,
  input: {
    nonce: string;
    participantId: string;
    environment: string;
    roomId: string;
    acceptedAt: number;
    expiresAt: number;
  },
): Promise<void> {
  try {
    await db
      .prepare(
        `INSERT INTO room_ticket_nonces (
          nonce, participant_id, environment, room_id, accepted_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        input.nonce,
        input.participantId,
        input.environment,
        input.roomId,
        input.acceptedAt,
        input.expiresAt,
      )
      .run();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("room_ticket_nonces")) {
      throw new HttpError(409, "room_ticket_replayed", "This room ticket has already been used.");
    }
    throw error;
  }
}

export async function getCurrentSnapshot(
  db: D1Database,
  environment: string,
): Promise<PublicActivitySnapshot | null> {
  const row = await db
    .prepare(
      `SELECT snapshot_json
       FROM current_public_state
       WHERE environment = ?`,
    )
    .bind(environment)
    .first<{ snapshot_json: string }>();

  if (!row) return null;

  let decoded: unknown;
  try {
    decoded = JSON.parse(row.snapshot_json);
  } catch {
    throw new HttpError(
      500,
      "invalid_stored_snapshot",
      "The stored public snapshot is not valid JSON.",
    );
  }

  const snapshot = normalizePublicActivitySnapshot(decoded);
  if (snapshot === null) {
    throw new HttpError(
      500,
      "invalid_stored_snapshot",
      "The stored public snapshot does not match a supported public schema.",
    );
  }
  return snapshot;
}

export async function publishSnapshot(
  db: D1Database,
  snapshot: PublicActivitySnapshot,
  bodySha256: string,
  nonceStatement: D1PreparedStatement,
): Promise<void> {
  try {
    await db.batch([
      nonceStatement,
      db
        .prepare(
          `INSERT INTO public_state_revisions (
            environment,
            revision,
            state_head_hash,
            previous_revision,
            previous_state_head_hash,
            snapshot_json,
            payload_sha256,
            published_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          snapshot.environment,
          snapshot.revision,
          snapshot.stateHeadHash,
          snapshot.revision === 1 ? null : snapshot.revision - 1,
          snapshot.previousStateHeadHash,
          JSON.stringify(snapshot),
          bodySha256,
          snapshot.updatedAt,
        ),
      db
        .prepare(
          `INSERT INTO current_public_state (
            environment,
            revision,
            state_head_hash,
            previous_state_head_hash,
            snapshot_json,
            payload_sha256,
            updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(environment) DO UPDATE SET
            revision = excluded.revision,
            state_head_hash = excluded.state_head_hash,
            previous_state_head_hash = excluded.previous_state_head_hash,
            snapshot_json = excluded.snapshot_json,
            payload_sha256 = excluded.payload_sha256,
            updated_at = excluded.updated_at`,
        )
        .bind(
          snapshot.environment,
          snapshot.revision,
          snapshot.stateHeadHash,
          snapshot.previousStateHeadHash,
          JSON.stringify(snapshot),
          bodySha256,
          snapshot.updatedAt,
        ),
    ]);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("UNIQUE constraint failed: hypha_request_nonces.nonce")) {
      throw new HttpError(409, "replayed_request", "The Hypha nonce has already been used.");
    }
    if (
      detail.includes("state revision must increase") ||
      detail.includes("previous state head") ||
      detail.includes("first state revision") ||
      detail.includes("FOREIGN KEY constraint failed") ||
      detail.includes("CHECK constraint failed") ||
      detail.includes("UNIQUE constraint failed: public_state_revisions")
    ) {
      throw new HttpError(409, "state_chain_conflict", detail);
    }
    throw error;
  }
}

export async function getArtifactFile(
  db: D1Database,
  environment: string,
  artifactId: string,
  filename: string,
): Promise<ArtifactFileRow | null> {
  return db
    .prepare(
      `SELECT environment, artifact_id, filename, object_key, content_type,
              byte_length, content_sha256, uploaded_at
       FROM published_artifact_files
       WHERE environment = ? AND artifact_id = ? AND filename = ?`,
    )
    .bind(environment, artifactId, filename)
    .first<ArtifactFileRow>();
}

export async function listArtifactFiles(
  db: D1Database,
  environment: string,
  artifactId: string,
): Promise<ArtifactFileRow[]> {
  const result = await db
    .prepare(
      `SELECT environment, artifact_id, filename, object_key, content_type,
              byte_length, content_sha256, uploaded_at
       FROM published_artifact_files
       WHERE environment = ? AND artifact_id = ?
       ORDER BY filename`,
    )
    .bind(environment, artifactId)
    .all<ArtifactFileRow>();
  return result.results ?? [];
}

export async function registerArtifactFile(
  db: D1Database,
  input: ArtifactFileRow,
  nonceStatement: D1PreparedStatement,
): Promise<void> {
  try {
    await db.batch([
      nonceStatement,
      db
        .prepare(
          `INSERT INTO published_artifact_files (
            environment, artifact_id, filename, object_key, content_type,
            byte_length, content_sha256, uploaded_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          input.environment,
          input.artifact_id,
          input.filename,
          input.object_key,
          input.content_type,
          input.byte_length,
          input.content_sha256,
          input.uploaded_at,
        ),
    ]);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("hypha_request_nonces.nonce")) {
      throw new HttpError(409, "replayed_request", "The Hypha nonce has already been used.");
    }
    if (detail.includes("published_artifact_files")) {
      throw new HttpError(409, "artifact_file_conflict", "That artifact filename is already registered.");
    }
    throw error;
  }
}

export async function getLatestPublication(
  db: D1Database,
  environment: string,
): Promise<PublicationPayload | null> {
  const row = await db
    .prepare(
      `SELECT publication_json
       FROM public_publications
       WHERE environment = ?
       ORDER BY published_at DESC, publication_id DESC
       LIMIT 1`,
    )
    .bind(environment)
    .first<LatestPublicationRow>();
  if (!row) return null;
  return JSON.parse(row.publication_json) as PublicationPayload;
}

async function requireArtifactFiles(
  db: D1Database,
  payload: PublicationPayload,
): Promise<void> {
  const checks: Array<[string, string]> = [
    [payload.primaryFilename, "missing_primary_asset"],
  ];
  if (payload.manifestFilename) {
    checks.push([payload.manifestFilename, "missing_manifest"]);
  }
  if (payload.visualizationFilename) {
    checks.push([payload.visualizationFilename, "missing_visualization_spec"]);
  }
  if (payload.dataFilename) {
    checks.push([payload.dataFilename, "missing_visualization_data"]);
  }

  for (const [filename, code] of checks) {
    const file = await getArtifactFile(
      db,
      payload.environment,
      payload.artifactId,
      filename,
    );
    if (!file) {
      throw new HttpError(
        409,
        code,
        `The publication references an unregistered artifact file: ${filename}.`,
      );
    }
  }
}

export async function publishPublication(
  db: D1Database,
  payload: PublicationPayload,
  rawJson: string,
  nonceStatement: D1PreparedStatement,
): Promise<void> {
  const current = await db
    .prepare(
      `SELECT state_head_hash
       FROM current_public_state
       WHERE environment = ?`,
    )
    .bind(payload.environment)
    .first<{ state_head_hash: string }>();
  if (!current || current.state_head_hash !== payload.stateHeadHash) {
    throw new HttpError(
      409,
      "publication_state_conflict",
      "The publication does not reference the current public state head.",
    );
  }

  await requireArtifactFiles(db, payload);

  try {
    await db.batch([
      nonceStatement,
      db
        .prepare(
          `INSERT INTO public_publications (
            environment, publication_id, artifact_id, state_head_hash, title,
            public_summary, limitation, primary_filename, manifest_filename,
            publication_json, published_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          payload.environment,
          payload.publicationId,
          payload.artifactId,
          payload.stateHeadHash,
          payload.title,
          payload.publicSummary,
          payload.limitation,
          payload.primaryFilename,
          payload.manifestFilename,
          rawJson,
          payload.publishedAt,
        ),
    ]);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("hypha_request_nonces.nonce")) {
      throw new HttpError(409, "replayed_request", "The Hypha nonce has already been used.");
    }
    if (detail.includes("public_publications")) {
      throw new HttpError(409, "publication_conflict", "That publication ID already exists.");
    }
    throw error;
  }
}

export async function createSession(
  db: D1Database,
  input: SessionRow,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO activity_sessions (
        session_hash, participant_id, display_name, avatar_url,
        discord_user_id, instance_id, guild_id, channel_id,
        issued_at, expires_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      input.session_hash,
      input.participant_id,
      input.display_name,
      input.avatar_url,
      input.discord_user_id,
      input.instance_id,
      input.guild_id,
      input.channel_id,
      input.issued_at,
      input.expires_at,
      input.last_seen_at,
    )
    .run();
}

export async function getSession(
  db: D1Database,
  sessionHash: string,
  nowSeconds: number,
): Promise<SessionRow | null> {
  const row = await db
    .prepare(
      `SELECT session_hash, participant_id, display_name, avatar_url,
              discord_user_id, instance_id, guild_id, channel_id,
              issued_at, expires_at, last_seen_at
       FROM activity_sessions
       WHERE session_hash = ? AND expires_at >= ?`,
    )
    .bind(sessionHash, nowSeconds)
    .first<SessionRow>();

  if (row) {
    await db
      .prepare("UPDATE activity_sessions SET last_seen_at = ? WHERE session_hash = ?")
      .bind(nowSeconds, sessionHash)
      .run();
  }
  return row;
}

export async function deleteSession(
  db: D1Database,
  sessionHash: string,
): Promise<void> {
  await db
    .prepare("DELETE FROM activity_sessions WHERE session_hash = ?")
    .bind(sessionHash)
    .run();
}


export interface HyphaChatRequestRow {
  request_id: string;
  participant_id: string;
  discord_user_id: string;
  privacy_alias: string | null;
  environment: string;
  stream_id: string;
  message_text: string;
  status: "pending" | "processing" | "complete" | "failed";
  participant_message_id: string;
  hypha_message_id: string;
  created_at: number;
  claimed_at: number | null;
  completed_at: number | null;
  expires_at: number;
  albuquerque_mode: number;
}

export interface HyphaChatMessageRow {
  row_id: number;
  message_id: string;
  request_id: string;
  environment: string;
  stream_id: string;
  sender_type: "participant" | "hypha";
  participant_id: string | null;
  working_name: string | null;
  content_text: string;
  delivery_status: "pending" | "processing" | "complete" | "failed";
  audio_available: number;
  created_at: number;
  completed_at: number | null;
}

const HYPHA_CHAT_REQUEST_COLUMNS = `request_id, participant_id, discord_user_id,
  privacy_alias, environment, stream_id, message_text, status,
  participant_message_id, hypha_message_id, created_at, claimed_at,
  completed_at, expires_at, albuquerque_mode`;
const HYPHA_CHAT_MESSAGE_COLUMNS = `row_id, message_id, request_id,
  environment, stream_id, sender_type, participant_id, working_name,
  content_text, delivery_status, audio_available, created_at, completed_at`;

export async function createHyphaChatRequest(
  db: D1Database,
  input: {
    requestId: string;
    participantId: string;
    discordUserId: string;
    privacyAlias: string | null;
    environment: string;
    streamId: string;
    workingName: string;
    participantMessageId: string;
    hyphaMessageId: string;
    messageText: string;
    createdAt: number;
    expiresAt: number;
    albuquerqueMode: boolean;
  },
): Promise<void> {
  await db.batch([
    db.prepare(
      `INSERT INTO hypha_chat_requests (
        request_id, participant_id, discord_user_id, privacy_alias,
        environment, stream_id, message_text, status,
        participant_message_id, hypha_message_id, created_at, expires_at,
        albuquerque_mode
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)`,
    ).bind(input.requestId, input.participantId, input.discordUserId,
      input.privacyAlias, input.environment, input.streamId, input.messageText,
      input.participantMessageId, input.hyphaMessageId, input.createdAt,
      input.expiresAt, input.albuquerqueMode ? 1 : 0),
    db.prepare(
      `INSERT INTO hypha_chat_messages (
        message_id, request_id, environment, stream_id, sender_type,
        participant_id, working_name, content_text, delivery_status,
        created_at, completed_at
      ) VALUES (?, ?, ?, ?, 'participant', ?, ?, ?, 'complete', ?, ?)`,
    ).bind(input.participantMessageId, input.requestId, input.environment,
      input.streamId, input.participantId, input.workingName,
      input.messageText, input.createdAt, input.createdAt),
    db.prepare(
      `INSERT INTO hypha_chat_messages (
        message_id, request_id, environment, stream_id, sender_type,
        content_text, delivery_status, created_at
      ) VALUES (?, ?, ?, ?, 'hypha', '', 'pending', ?)`,
    ).bind(input.hyphaMessageId, input.requestId, input.environment,
      input.streamId, input.createdAt),
  ]);
}

export async function getHyphaChatRequest(
  db: D1Database,
  requestId: string,
): Promise<HyphaChatRequestRow | null> {
  return db
    .prepare(
      `SELECT ${HYPHA_CHAT_REQUEST_COLUMNS}
       FROM hypha_chat_requests
       WHERE request_id = ?`,
    )
    .bind(requestId)
    .first<HyphaChatRequestRow>();
}

export async function claimNextHyphaChatRequest(
  db: D1Database,
  nowSeconds: number,
  environment: string,
  streamId: string,
): Promise<HyphaChatRequestRow | null> {
  const candidate = await db
    .prepare(
      `SELECT ${HYPHA_CHAT_REQUEST_COLUMNS}
       FROM hypha_chat_requests
       WHERE environment = ? AND stream_id = ?
         AND status = 'pending' AND expires_at >= ?
       ORDER BY created_at, request_id
       LIMIT 1`,
    )
    .bind(environment, streamId, nowSeconds)
    .first<HyphaChatRequestRow>();

  if (!candidate) return null;

  const results = await db.batch([
    db.prepare(
      `UPDATE hypha_chat_requests
       SET status = 'processing', claimed_at = ?
       WHERE request_id = ? AND environment = ? AND stream_id = ?
         AND status = 'pending'`,
    )
    .bind(nowSeconds, candidate.request_id, environment, streamId),
    db.prepare(
      `UPDATE hypha_chat_messages SET delivery_status = 'processing'
       WHERE message_id = ? AND environment = ? AND stream_id = ?
         AND delivery_status = 'pending' AND EXISTS (
           SELECT 1 FROM hypha_chat_requests WHERE request_id = ?
             AND status = 'processing' AND claimed_at = ?
         )`,
    ).bind(candidate.hypha_message_id, environment, streamId,
      candidate.request_id, nowSeconds),
  ]);

  if ((results[0]?.meta?.changes ?? 0) !== 1) return null;
  return {
    ...candidate,
    status: "processing",
    claimed_at: nowSeconds,
  };
}

export async function completeHyphaChatRequest(
  db: D1Database,
  input: {
    requestId: string;
    environment: string;
    streamId: string;
    transcriptText: string;
    audioBytes: Uint8Array | null;
    completedAt: number;
    failed: boolean;
  },
): Promise<void> {
  const row = await getHyphaChatRequest(db, input.requestId);
  if (!row || row.status !== "processing" ||
      row.environment !== input.environment || row.stream_id !== input.streamId) {
    throw new HttpError(
      409,
      "hypha_chat_state_conflict",
      "The Hypha chat request is not in processing state.",
    );
  }
  const messageUpdate = db.prepare(
    `UPDATE hypha_chat_messages
     SET content_text = ?, delivery_status = ?, audio_available = ?, completed_at = ?
     WHERE message_id = ? AND environment = ? AND stream_id = ?
       AND delivery_status = 'processing' AND EXISTS (
         SELECT 1 FROM hypha_chat_requests
         WHERE request_id = ? AND status = 'processing'
       )`,
  ).bind(input.transcriptText, input.failed ? "failed" : "complete",
    input.audioBytes ? 1 : 0, input.completedAt, row.hypha_message_id,
    input.environment, input.streamId, input.requestId);
  const statements = [messageUpdate];
  if (input.audioBytes) {
    statements.push(db.prepare(
      `INSERT INTO hypha_chat_audio (message_id, audio_bytes, created_at)
       SELECT ?, ?, ? WHERE EXISTS (
         SELECT 1 FROM hypha_chat_requests
         WHERE request_id = ? AND status = 'processing'
       )`,
    ).bind(row.hypha_message_id, input.audioBytes, input.completedAt,
      input.requestId));
  }
  statements.push(db.prepare(
    `UPDATE hypha_chat_requests SET status = ?, completed_at = ?
     WHERE request_id = ? AND environment = ? AND stream_id = ?
       AND status = 'processing'`,
  ).bind(input.failed ? "failed" : "complete", input.completedAt,
    input.requestId, input.environment, input.streamId));
  const results = await db.batch(statements);
  if ((results.at(-1)?.meta?.changes ?? 0) !== 1 ||
      (results[0]?.meta?.changes ?? 0) !== 1) {
    throw new HttpError(409, "hypha_chat_state_conflict",
      "The Hypha chat request changed before completion.");
  }
}

export async function listHyphaChatMessages(
  db: D1Database,
  environment: string,
  streamId: string,
  limit: number,
  beforeId: string | null,
  afterId: string | null,
): Promise<{ messages: HyphaChatMessageRow[]; hasMore: boolean }> {
  let cursor: number | null = null;
  if (beforeId || afterId) {
    const row = await db.prepare(
      `SELECT row_id FROM hypha_chat_messages
       WHERE message_id = ? AND environment = ? AND stream_id = ?`,
    ).bind(beforeId ?? afterId, environment, streamId)
      .first<{ row_id: number }>();
    if (!row) throw new HttpError(400, "invalid_chat_cursor",
      "The chat cursor is unavailable in this investigation.");
    cursor = row.row_id;
  }
  const forward = afterId !== null;
  const result = await db.prepare(
    `SELECT ${HYPHA_CHAT_MESSAGE_COLUMNS} FROM hypha_chat_messages
     WHERE environment = ? AND stream_id = ?
       ${cursor === null ? "" : `AND row_id ${forward ? ">" : "<"} ?`}
     ORDER BY row_id ${forward ? "ASC" : "DESC"} LIMIT ?`,
  ).bind(...(cursor === null
    ? [environment, streamId, limit + 1]
    : [environment, streamId, cursor, limit + 1]))
    .all<HyphaChatMessageRow>();
  const rows = (result.results ?? []).slice(0, limit);
  return { messages: forward ? rows : rows.reverse(),
    hasMore: (result.results?.length ?? 0) > limit };
}

export async function getHyphaChatMessage(
  db: D1Database,
  messageId: string,
  environment: string,
  streamId: string,
): Promise<HyphaChatMessageRow | null> {
  return db.prepare(
    `SELECT ${HYPHA_CHAT_MESSAGE_COLUMNS} FROM hypha_chat_messages
     WHERE message_id = ? AND environment = ? AND stream_id = ?`,
  ).bind(messageId, environment, streamId).first<HyphaChatMessageRow>();
}

export async function getHyphaChatMessagesForRequest(
  db: D1Database,
  requestId: string,
  environment: string,
  streamId: string,
): Promise<HyphaChatMessageRow[]> {
  const result = await db.prepare(
    `SELECT ${HYPHA_CHAT_MESSAGE_COLUMNS} FROM hypha_chat_messages
     WHERE request_id = ? AND environment = ? AND stream_id = ?
     ORDER BY row_id ASC`,
  ).bind(requestId, environment, streamId).all<HyphaChatMessageRow>();
  return result.results ?? [];
}

export async function recentHyphaChatConversation(
  db: D1Database,
  environment: string,
  streamId: string,
  beforeMessageId: string,
): Promise<Array<{ sender_type: "participant" | "hypha"; content_text: string }>> {
  const result = await db.prepare(
    `SELECT sender_type, content_text FROM hypha_chat_messages
     WHERE environment = ? AND stream_id = ? AND delivery_status = 'complete'
       AND content_text <> '' AND row_id < (
         SELECT row_id FROM hypha_chat_messages
         WHERE message_id = ? AND environment = ? AND stream_id = ?
       )
     ORDER BY row_id DESC LIMIT 8`,
  ).bind(environment, streamId, beforeMessageId, environment, streamId)
    .all<{ sender_type: "participant" | "hypha"; content_text: string }>();
  return (result.results ?? []).reverse();
}

export async function getHyphaChatAudio(
  db: D1Database,
  messageId: string,
): Promise<{ audio_bytes: number[] } | null> {
  return db.prepare("SELECT audio_bytes FROM hypha_chat_audio WHERE message_id = ?")
    .bind(messageId).first<{ audio_bytes: number[] }>();
}
