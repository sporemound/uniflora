import {
  Common,
  DiscordSDK,
  Platform,
  patchUrlMappings,
} from "@discord/embedded-app-sdk";
import {
  dispatchActivityExternalLink,
  type ExternalLinkDispatchResult,
} from "./activity-link-navigation";

let readyDiscordSdk: DiscordSDK | null = null;

function thermalStateName(
  thermalState: -1 | 0 | 1 | 2 | 3,
): "unhandled" | "nominal" | "fair" | "serious" | "critical" {
  switch (thermalState) {
    case 0:
      return "nominal";
    case 1:
      return "fair";
    case 2:
      return "serious";
    case 3:
      return "critical";
    default:
      return "unhandled";
  }
}

function configureActivityDisplay(sdk: DiscordSDK): void {
  const root = document.documentElement;
  root.dataset.discordPlatform =
    sdk.platform === Platform.MOBILE ? "mobile" : "desktop";

  if (sdk.mobileAppVersion) {
    root.dataset.discordMobile = "true";
  }

  // The workspace supports both phone orientations. PIP and grid views remain
  // landscape so maps and scientific plots retain a useful minimum width.
  void sdk.commands
    .setOrientationLockState({
      lock_state: Common.OrientationLockStateTypeObject.UNLOCKED,
      picture_in_picture_lock_state:
        Common.OrientationLockStateTypeObject.LANDSCAPE,
      grid_lock_state: Common.OrientationLockStateTypeObject.LANDSCAPE,
    })
    .catch(() => {
      // Older Discord clients can omit orientation commands.
    });

  void sdk
    .subscribe("THERMAL_STATE_UPDATE", ({ thermal_state }) => {
      root.dataset.thermalState = thermalStateName(thermal_state);
    })
    .catch(() => {
      // Android versions before 10 and older Discord clients may omit updates.
    });
}

export const DISCORD_EXTERNAL_URL_MAPPINGS = [
  {
    prefix: "/external/carto",
    target: "a.basemaps.cartocdn.com",
  },
  {
    prefix: "/external/nasa-gibs",
    target: "gibs.earthdata.nasa.gov",
  },
  {
    prefix: "/external/noaa-radar",
    target: "mapservices.weather.noaa.gov",
  },
  {
    prefix: "/external/nws-alerts",
    target: "api.weather.gov",
  },
] as const;

if (import.meta.env.VITE_ENABLE_DISCORD_SDK === "true") {
  // This must run before MapLibre or the environmental layer bus makes its
  // first request through Discord's sandboxed Activity proxy.
  patchUrlMappings([...DISCORD_EXTERNAL_URL_MAPPINGS]);
}

export interface PublicParticipant {
  participantId: string;
  displayName: string;
  avatarUrl: string | null;
}

interface AuthExchangeResponse {
  accessToken: string;
  sessionToken: string;
  expiresAt: number;
  participant: PublicParticipant;
  environment: "test" | "live";
}

export type DiscordConnectionState =
  | {
      status: "browser-preview";
      detail: string;
      participant: null;
      sessionToken: null;
      instanceId: null;
      launchCustomId: null;
    }
  | {
      status: "connecting";
      detail: string;
      participant: null;
      sessionToken: null;
      instanceId: null;
      launchCustomId: null;
    }
  | {
      status: "ready";
      detail: string;
      participant: PublicParticipant;
      sessionToken: string;
      instanceId: string;
      launchCustomId: string | null;
      environment: "test" | "live";
    }
  | {
      status: "error";
      detail: string;
      participant: null;
      sessionToken: null;
      instanceId: null;
      launchCustomId: null;
    };

async function exchangeCode(
  code: string,
  instanceId: string,
): Promise<AuthExchangeResponse> {
  const response = await fetch("/api/auth/discord", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code, instanceId }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Discord token exchange failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as AuthExchangeResponse;
}

function connectionErrorDetail(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error.slice(0, 300);
  if (error && typeof error === "object") {
    const value = error as Record<string, unknown>;
    const code = typeof value.code === "string" || typeof value.code === "number"
      ? String(value.code).slice(0, 80) : null;
    const message = typeof value.message === "string"
      ? value.message.slice(0, 300) : null;
    return [code, message].filter(Boolean).join(": ") || "SDK returned an error without a message.";
  }
  return "SDK returned an error without a message.";
}

export async function connectDiscord(): Promise<DiscordConnectionState> {
  const enabled = import.meta.env.VITE_ENABLE_DISCORD_SDK === "true";
  const clientId = import.meta.env.VITE_DISCORD_CLIENT_ID?.trim();

  if (!enabled) {
    return {
      status: "browser-preview",
      detail: "Discord SDK and OAuth are disabled for ordinary browser development.",
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    };
  }

  if (!clientId) {
    return {
      status: "error",
      detail: "VITE_DISCORD_CLIENT_ID is required when the Discord SDK is enabled.",
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    };
  }

  if (!new URLSearchParams(window.location.search).has("frame_id")) {
    return {
      status: "browser-preview",
      detail: "This web link is a preview. In the live Discord channel, open the App Launcher, choose The Missing Interior, and select Launch to join the Activity.",
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    };
  }

  let step = "initialization";
  try {
    const sdk = new DiscordSDK(clientId, {
      disableConsoleLogOverride: true,
    });
    const instanceId = sdk.instanceId;
    if (!instanceId) {
      throw new Error("Discord did not provide an Activity instance ID.");
    }

    step = "handshake";
    await Promise.race([
      sdk.ready(),
      new Promise<never>((_, reject) => {
        window.setTimeout(
          () => reject(new Error("Discord SDK handshake timed out.")),
          12_000,
        );
      }),
    ]);
    // External links require only a ready SDK, not OAuth. Retain this bridge
    // even if the later identity/session exchange fails.
    readyDiscordSdk = sdk;
    configureActivityDisplay(sdk);

    step = "authorization";
    const authorization = await sdk.commands.authorize({
      client_id: clientId,
      response_type: "code",
      state: "",
      prompt: "none",
      scope: ["identify"],
    });
    step = "token exchange";
    const exchange = await exchangeCode(authorization.code, instanceId);
    step = "session authentication";
    await sdk.commands.authenticate({
      access_token: exchange.accessToken,
    });
    const launchCustomId =
      typeof sdk.customId === "string" && sdk.customId.trim()
        ? sdk.customId.trim()
        : null;

    return {
      status: "ready",
      detail: `Authenticated as ${exchange.participant.displayName}.`,
      participant: exchange.participant,
      sessionToken: exchange.sessionToken,
      instanceId,
      launchCustomId,
      environment: exchange.environment,
    };
  } catch (error) {
    return {
      status: "error",
      detail: `Discord ${step} failed: ${connectionErrorDetail(error)}`,
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    };
  }
}

export function usesDiscordExternalLinks(): boolean {
  return import.meta.env.VITE_ENABLE_DISCORD_SDK === "true";
}

export async function openExternalActivityLink(
  url: string,
): Promise<ExternalLinkDispatchResult> {
  if (usesDiscordExternalLinks()) {
    return dispatchActivityExternalLink({
      runtime: "discord-activity",
      href: url,
      discordCommand: readyDiscordSdk?.commands ?? null,
    });
  }
  return dispatchActivityExternalLink({
    runtime: "browser-preview",
    href: url,
    openWindow: (href, target, features) =>
      window.open(href, target, features),
  });
}
