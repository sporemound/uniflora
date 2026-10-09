import type { EnvironmentName } from "../../src/shared/public-state";
import { requireSession } from "./auth";
import { HttpError } from "./errors";
import {
  readWebSession,
  requireSameOriginMutation,
  type MagicLinkEnv,
} from "./magic-link-auth";

export interface PrincipalEnv extends MagicLinkEnv {
  ACTIVITY_ALLOWED_TEST_CHANNEL_ID?: string;
  ACTIVITY_ALLOWED_LIVE_CHANNEL_ID?: string;
}

export interface ActivityPrincipal {
  authProvider: "discord" | "email";
  participantId: string;
  displayName: string;
  avatarUrl: string | null;
  environment: EnvironmentName;
  /** Legacy relay column; web values are `web:<opaque participant ID>`. */
  subjectKey: string;
  discordInstanceId: string | null;
}

export function hasActivityCredential(request: Request): boolean {
  if (request.headers.has("Authorization")) return true;
  return /(?:^|;)\s*(?:__Host-mi_session|mi_dev_session)=/u.test(
    request.headers.get("Cookie") ?? "",
  );
}

export async function requireActivityPrincipal(
  request: Request,
  env: PrincipalEnv,
): Promise<ActivityPrincipal> {
  if (request.headers.has("Authorization")) {
    const session = await requireSession(env.PUBLIC_DB, request);
    let environment: EnvironmentName;
    if (session.channelId && session.channelId === env.ACTIVITY_ALLOWED_TEST_CHANNEL_ID) {
      environment = "test";
    } else if (session.channelId && session.channelId === env.ACTIVITY_ALLOWED_LIVE_CHANNEL_ID) {
      environment = "live";
    } else {
      throw new HttpError(403, "activity_access_denied", "This channel has no Activity access.");
    }
    return {
      authProvider: "discord",
      participantId: session.participantId,
      displayName: session.displayName,
      avatarUrl: session.avatarUrl,
      environment,
      subjectKey: session.discordUserId,
      discordInstanceId: session.instanceId,
    };
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    requireSameOriginMutation(request, env);
  }
  const session = await readWebSession(request, env);
  if (!session) {
    throw new HttpError(401, "missing_session", "A valid investigation session is required.");
  }
  return {
    authProvider: "email",
    participantId: session.participant.participantId,
    displayName: session.participant.displayName,
    avatarUrl: session.participant.avatarUrl,
    environment: "live",
    subjectKey: `web:${session.participant.participantId}`,
    discordInstanceId: null,
  };
}
