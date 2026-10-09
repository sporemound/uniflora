import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import { unstable_splitSqlQuery } from "wrangler";

const previewDir = new URL("../preview-migrations/", import.meta.url);
const legacyDir = new URL("../migrations/", import.meta.url);
const expected = [
  "0001_phase2_public_sync.sql",
  "0002_phase4_room_tickets.sql",
  "0003_activity_instance_sessions.sql",
  "0004_web_magic_links_preview_quota.sql",
];
assert.deepEqual((await readdir(previewDir)).sort(), expected,
  "preview migrations must not include unrelated Activity migrations");
for (const filename of expected.slice(0, 3)) {
  const preview = await readFile(new URL(filename, previewDir));
  const legacy = await readFile(new URL(filename, legacyDir));
  assert.ok(preview.equals(legacy), `${filename} must match the already-applied migration exactly`);
}
const previewAuth = await readFile(new URL(expected[3], previewDir), "utf8");
const originalAuth = await readFile(new URL("0006_web_magic_links.sql", legacyDir), "utf8");
const originalQuota = await readFile(new URL("0007_preview_email_quota.sql", legacyDir), "utf8");
const normalized = (sql) => unstable_splitSqlQuery(sql).map((statement) =>
  statement.replace(/\s+/gu, " ").trim());
assert.deepEqual(normalized(previewAuth), [
  ...normalized(originalAuth), ...normalized(originalQuota),
], "preview auth migration must preserve the existing web-auth and quota SQL statements");

const db = new DatabaseSync(":memory:");
try {
  db.exec("PRAGMA foreign_keys = ON");
  for (const filename of expected) {
    const sql = await readFile(new URL(filename, previewDir), "utf8");
    const statements = unstable_splitSqlQuery(sql);
    assert.ok(statements.length > 0, `${filename} has no SQL statements`);
    for (const statement of statements) {
      db.exec(statement);
    }
  }
  const tableNames = new Set(db.prepare(
    "SELECT name FROM sqlite_master WHERE type = 'table'",
  ).all().map((row) => row.name));
  for (const table of [
    "current_public_state", "public_state_revisions", "hypha_request_nonces",
    "activity_sessions", "room_ticket_nonces", "web_magic_links",
    "web_magic_link_cooldowns", "preview_magic_link_quota",
  ]) {
    assert.ok(tableNames.has(table), `${table} must be available to the preview Worker`);
  }
  const sessionColumns = new Set(db.prepare(
    "PRAGMA table_info(activity_sessions)",
  ).all().map((column) => column.name));
  for (const column of ["participant_id", "discord_user_id", "auth_provider", "email_hash"]) {
    assert.ok(sessionColumns.has(column), `activity_sessions.${column} is required`);
  }
} finally {
  db.close();
}

console.log("Preview-only public migrations parse and create the required schema.");
