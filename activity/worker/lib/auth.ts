import type { D1Database } from "./cloudflare";
import { hmacSha256Hex, randomToken, sha256Hex } from "./crypto";
import { createSession, deleteSession, getSession } from "./database";
import { HttpError } from "./errors";

interface DiscordTokenResponse {
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  scope?: string;
  error?: string;
  error_description?: string;
}

interface DiscordUser {
  id: string;
  username: string;
  global_name?: string | null;
  avatar?: string | null;
}

interface DiscordActivityInstance {
  application_id?: string;
  instance_id?: string;
  location?: {
    kind?: string;
    guild_id?: string;
    channel_id?: string;
  };
  users?: string[];
}

export interface ActivityParticipant {
  participantId: string;
  displayName: string;
  avatarUrl: string | null;
}

export interface ActivitySession extends ActivityParticipant {
  discordUserId: string;
  instanceId: string;
  guildId: string;
  channelId: string;
}

export interface DiscordAuthResult {
  accessToken: string;
  sessionToken: string;
  expiresAt: number;
  participant: ActivityParticipant;
  environment: "test" | "live";
}

function avatarUrl(user: DiscordUser): string | null {
  if (!user.avatar) {
    return null;
  }
  return `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=128`;
}

function requiredDiscordId(value: string, label: string): string {
  const normalized = value.trim();
  if (!/^[1-9][0-9]{15,21}$/u.test(normalized)) {
    throw new HttpError(
      503,
      "discord_access_unconfigured",
      `${label} is not configured as a Discord snowflake.`,
    );
  }
  return normalized;
}

function allowedDiscordUsers(value: string): ReadonlySet<string> {
  const ids = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (
    ids.length === 0 ||
    ids.some((item) => !/^[1-9][0-9]{15,21}$/u.test(item))
  ) {
    throw new HttpError(
      503,
      "discord_access_unconfigured",
      "The Activity Discord-user allowlist is missing or invalid.",
    );
  }
  return new Set(ids);
}

async function requireActivityInstance(input: {
  clientId: string;
  botToken: string;
  instanceId: string;
  userId: string;
  guildId: string;
  allowedChannelIds: ReadonlySet<string>;
}): Promise<string> {
  if (
    !/^[A-Za-z0-9_-]{16,256}$/u.test(input.instanceId) ||
    !input.botToken.trim()
  ) {
    throw new HttpError(
      503,
      "discord_instance_validation_unconfigured",
      "Discord Activity-instance validation is not configured.",
    );
  }
  const response = await fetch(
    `https://discord.com/api/v10/applications/${input.clientId}/activity-instances/${encodeURIComponent(input.instanceId)}`,
    {
      headers: {
        Accept: "application/json",
        Authorization: `Bot ${input.botToken}`,
      },
    },
  );
  const value = (await response.json().catch(() => null)) as
    | DiscordActivityInstance
    | null;
  if (response.status === 404) {
    throw new HttpError(
      401,
      "discord_instance_invalid",
      "Discord does not recognize this active Activity instance.",
    );
  }
  if (!response.ok || value === null) {
    throw new HttpError(
      503,
      "discord_instance_validation_failed",
      `Discord Activity-instance validation returned HTTP ${response.status}.`,
    );
  }
  if (
    value.application_id !== input.clientId ||
    value.instance_id !== input.instanceId ||
    value.location?.kind !== "gc" ||
    value.location.guild_id !== input.guildId ||
    !value.location.channel_id ||
    !input.allowedChannelIds.has(value.location.channel_id) ||
    !Array.isArray(value.users) ||
    !value.users.includes(input.userId)
  ) {
    throw new HttpError(
      403,
      "discord_activity_access_denied",
      "This Activity session is outside the configured investigation channels.",
    );
  }
  return value.location.channel_id;
}

export async function exchangeDiscordCode(
  db: D1Database,
  input: {
    code: string;
    instanceId: string;
    clientId: string;
    clientSecret: string;
    botToken: string;
    allowedGuildId: string;
    allowedChannelId: string;
    allowedLiveChannelId?: string;
    livePlayerRoleId?: string;
    allowedDiscordUserIds: string;
    identitySecret: string;
    sessionTtlSeconds: number;
  },
): Promise<DiscordAuthResult> {
  if (
    !input.clientId ||
    !input.clientSecret ||
    !input.botToken ||
    input.identitySecret.length < 32
  ) {
    throw new HttpError(503, "discord_auth_unconfigured", "Discord authentication is not configured.");
  }
  const clientId = requiredDiscordId(input.clientId, "DISCORD_CLIENT_ID");
  const guildId = requiredDiscordId(input.allowedGuildId, "ACTIVITY_ALLOWED_GUILD_ID");
  const channelId = requiredDiscordId(
    input.allowedChannelId,
    "ACTIVITY_ALLOWED_TEST_CHANNEL_ID",
  );
  const liveChannelId = input.allowedLiveChannelId?.trim()
    ? requiredDiscordId(input.allowedLiveChannelId, "ACTIVITY_ALLOWED_LIVE_CHANNEL_ID") : null;
  const livePlayerRoleId = input.livePlayerRoleId?.trim()
    ? requiredDiscordId(input.livePlayerRoleId, "ACTIVITY_LIVE_PLAYER_ROLE_ID") : null;
  if (liveChannelId === channelId) {
    throw new HttpError(503, "discord_access_unconfigured", "Live and test channels must differ.");
  }
  const allowedUsers = allowedDiscordUsers(input.allowedDiscordUserIds);
  if (!input.code || input.code.length > 2048) {
    throw new HttpError(400, "invalid_authorization_code", "A Discord authorization code is required.");
  }

  const tokenResponse = await fetch("https://discord.com/api/oauth2/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: input.clientSecret,
      grant_type: "authorization_code",
      code: input.code,
    }),
  });
  const token = (await tokenResponse.json().catch(() => null)) as
    | DiscordTokenResponse
    | null;
  if (!tokenResponse.ok || !token?.access_token) {
    throw new HttpError(
      401,
      "discord_token_exchange_failed",
      token?.error_description ?? token?.error ?? "Discord rejected the authorization code.",
    );
  }

  const userResponse = await fetch("https://discord.com/api/v10/users/@me", {
    headers: {
      Authorization: `Bearer ${token.access_token}`,
    },
  });
  if (!userResponse.ok) {
    throw new HttpError(401, "discord_identity_failed", "Discord identity verification failed.");
  }
  const user = (await userResponse.json().catch(() => null)) as DiscordUser | null;
  if (!user?.id || !user.username) {
    throw new HttpError(401, "discord_identity_invalid", "Discord returned an incomplete user identity.");
  }
  const verifiedChannelId = await requireActivityInstance({
    clientId,
    botToken: input.botToken,
    instanceId: input.instanceId,
    userId: user.id,
    guildId,
    allowedChannelIds: new Set(liveChannelId ? [channelId, liveChannelId] : [channelId]),
  });
  if (verifiedChannelId === channelId && !allowedUsers.has(user.id)) {
    throw new HttpError(403, "discord_activity_access_denied",
      "This Discord account is not allowed to enter the private Activity test.");
  }
  if (verifiedChannelId === liveChannelId && !allowedUsers.has(user.id)) {
    if (!livePlayerRoleId) {
      throw new HttpError(503, "discord_access_unconfigured",
        "The live Activity player role is not configured.");
    }
    const memberResponse = await fetch(
      `https://discord.com/api/v10/guilds/${guildId}/members/${user.id}`,
      { headers: { Authorization: `Bot ${input.botToken}` } },
    );
    const member = await memberResponse.json().catch(() => null) as { roles?: unknown } | null;
    if (!memberResponse.ok || !Array.isArray(member?.roles) ||
        !member.roles.includes(livePlayerRoleId)) {
      throw new HttpError(403, "discord_activity_access_denied",
        "This Discord account does not have the live investigator role.");
    }
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  const expiresAt = nowSeconds + Math.max(300, Math.min(input.sessionTtlSeconds, 86_400));
  const sessionToken = randomToken();
  const sessionHash = await sha256Hex(sessionToken);
  const participantId = `participant_${(await hmacSha256Hex(input.identitySecret, user.id)).slice(0, 24)}`;
  const participant: ActivityParticipant = {
    participantId,
    displayName: user.global_name?.trim() || user.username,
    avatarUrl: avatarUrl(user),
  };

  await createSession(db, {
    session_hash: sessionHash,
    participant_id: participant.participantId,
    display_name: participant.displayName,
    avatar_url: participant.avatarUrl,
    discord_user_id: user.id,
    instance_id: input.instanceId,
    guild_id: guildId,
    channel_id: verifiedChannelId,
    issued_at: nowSeconds,
    expires_at: expiresAt,
    last_seen_at: nowSeconds,
  });

  return {
    accessToken: token.access_token,
    sessionToken,
    expiresAt,
    participant,
    environment: verifiedChannelId === channelId ? "test" : "live",
  };
}

function bearerToken(request: Request): string {
  const header = request.headers.get("Authorization") ?? "";
  const match = /^Bearer\s+([a-f0-9]{64})$/i.exec(header);
  if (!match) {
    throw new HttpError(401, "missing_session", "A valid Activity session bearer token is required.");
  }
  return match[1];
}

export async function requireSession(
  db: D1Database,
  request: Request,
): Promise<ActivitySession> {
  const token = bearerToken(request);
  const hash = await sha256Hex(token);
  const row = await getSession(db, hash, Math.floor(Date.now() / 1000));
  if (!row) {
    throw new HttpError(401, "invalid_session", "The Activity session is missing or expired.");
  }
  if (
    !row.discord_user_id ||
    !row.instance_id ||
    !row.guild_id ||
    !row.channel_id
  ) {
    throw new HttpError(
      401,
      "invalid_session",
      "The Activity session predates required instance validation.",
    );
  }
  return {
    participantId: row.participant_id,
    displayName: row.display_name,
    avatarUrl: row.avatar_url,
    discordUserId: row.discord_user_id,
    instanceId: row.instance_id,
    guildId: row.guild_id,
    channelId: row.channel_id,
  };
}

export async function revokeSession(
  db: D1Database,
  request: Request,
): Promise<void> {
  const token = bearerToken(request);
  await deleteSession(db, await sha256Hex(token));
}
