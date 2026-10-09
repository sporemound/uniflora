export interface SiteParticipant {
  participantId: string;
  displayName: string;
  avatarUrl: string | null;
}

export type SiteConnectionState =
  | {
      status: "connecting" | "signed-out" | "error";
      detail: string;
      participant: null;
      sessionToken: null;
      instanceId: null;
      launchCustomId: null;
    }
  | {
      status: "ready";
      detail: string;
      participant: SiteParticipant;
      // Cookie sessions use this marker only to enable existing authenticated UI.
      // It is never sent as a bearer credential.
      sessionToken: "web-cookie";
      instanceId: null;
      launchCustomId: null;
      environment: "live" | "test";
    };

export function siteAuthHeaders(sessionToken: string | null): HeadersInit {
  return sessionToken && sessionToken !== "web-cookie"
    ? { Authorization: `Bearer ${sessionToken}` }
    : {};
}

export async function connectSite(previewOnly = false): Promise<SiteConnectionState> {
  try {
    const response = await fetch("/api/session", {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.status === 401) {
      return {
        status: "signed-out",
        detail: "Sign in by email to join the investigation.",
        participant: null,
        sessionToken: null,
        instanceId: null,
        launchCustomId: null,
      };
    }
    if (previewOnly && response.status === 503) {
      const failure = await response.json().catch(() => null) as { error?: string } | null;
      if (failure?.error === "web_auth_schema_unavailable" ||
          failure?.error === "web_auth_unconfigured") {
        return {
          status: "signed-out",
          detail: "Email sign-in is being configured for this preview.",
          participant: null,
          sessionToken: null,
          instanceId: null,
          launchCustomId: null,
        };
      }
    }
    if (!response.ok) throw new Error(`Session check failed (${response.status}).`);
    const value = await response.json() as Record<string, unknown>;
    const participant = value.participant as Record<string, unknown> | undefined;
    if (!participant || typeof participant.participantId !== "string" ||
        typeof participant.displayName !== "string") {
      throw new Error("Session response was incomplete.");
    }
    const environment = value.environment === "test" ? "test" : "live";
    return {
      status: "ready",
      detail: `Signed in as ${participant.displayName}.`,
      participant: {
        participantId: participant.participantId,
        displayName: participant.displayName,
        avatarUrl: typeof participant.avatarUrl === "string" ? participant.avatarUrl : null,
      },
      sessionToken: "web-cookie",
      instanceId: null,
      launchCustomId: null,
      environment,
    };
  } catch (error) {
    return {
      status: "error",
      detail: error instanceof Error ? error.message : "Could not check sign-in status.",
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    };
  }
}

export async function requestMagicLink(email: string): Promise<void> {
  const response = await fetch("/api/auth/magic-link/request", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => null) as { message?: string } | null;
    throw new Error(value?.message ?? `Sign-in request failed (${response.status}).`);
  }
}

export async function signOut(): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`Sign-out failed (${response.status}).`);
}
