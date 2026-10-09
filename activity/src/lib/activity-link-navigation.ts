export type ActivityLinkRuntime = "discord-activity" | "browser-preview";

export interface ActivityLinkInteraction {
  currentHref: string;
  href: string;
  runtime: ActivityLinkRuntime;
  target?: string | null;
  download?: boolean;
  button?: number;
  defaultPrevented?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

export type ActivityLinkDecision =
  | {
      intent: "ignore";
      reason: "default-prevented" | "non-primary" | "modifier" | "download";
    }
  | {
      intent: "internal";
      href: string;
      historyHref: string;
      fragment: string;
    }
  | {
      intent: "discord-external";
      href: string;
    }
  | {
      intent: "browser-default";
      href: string;
      external: boolean;
    }
  | {
      intent: "blocked";
      href: string | null;
      reason: "invalid-url" | "unsafe-protocol" | "credentials";
    };

function normalizedTarget(target: string | null | undefined): string {
  return target?.trim().toLowerCase() ?? "";
}

/**
 * Classifies an anchor activation without reading or mutating browser state.
 * Callers can use the decision to perform SPA navigation, invoke Discord's
 * external-link command, retain native browser behavior, or block the link.
 */
export function classifyActivityLink(
  interaction: ActivityLinkInteraction,
): ActivityLinkDecision {
  if (interaction.defaultPrevented) {
    return { intent: "ignore", reason: "default-prevented" };
  }
  if ((interaction.button ?? 0) !== 0) {
    return { intent: "ignore", reason: "non-primary" };
  }
  if (
    interaction.metaKey ||
    interaction.ctrlKey ||
    interaction.shiftKey ||
    interaction.altKey
  ) {
    return { intent: "ignore", reason: "modifier" };
  }
  if (interaction.download) {
    return { intent: "ignore", reason: "download" };
  }

  let current: URL;
  let destination: URL;
  try {
    current = new URL(interaction.currentHref);
    destination = new URL(interaction.href, current);
  } catch {
    return { intent: "blocked", href: null, reason: "invalid-url" };
  }

  if (destination.username || destination.password) {
    return {
      intent: "blocked",
      href: destination.href,
      reason: "credentials",
    };
  }

  if (destination.origin === current.origin) {
    const target = normalizedTarget(interaction.target);
    if (
      interaction.runtime === "browser-preview" &&
      target &&
      target !== "_self"
    ) {
      return {
        intent: "browser-default",
        href: destination.href,
        external: false,
      };
    }
    return {
      intent: "internal",
      href: destination.href,
      historyHref: `${destination.pathname}${destination.search}${destination.hash}`,
      fragment: destination.hash.startsWith("#")
        ? destination.hash.slice(1)
        : "",
    };
  }

  if (destination.protocol !== "https:") {
    return {
      intent: "blocked",
      href: destination.href,
      reason: "unsafe-protocol",
    };
  }

  if (interaction.runtime === "discord-activity") {
    return { intent: "discord-external", href: destination.href };
  }

  return {
    intent: "browser-default",
    href: destination.href,
    external: true,
  };
}

export interface DiscordExternalLinkCommand {
  openExternalLink(input: { url: string }): Promise<{
    opened: boolean | null;
  }>;
}

export type BrowserWindowOpener = (
  url: string,
  target: "_blank",
  features: "noopener,noreferrer",
) => unknown | null;

export type ExternalLinkDispatchRequest =
  | {
      runtime: "discord-activity";
      href: string;
      discordCommand: DiscordExternalLinkCommand | null;
    }
  | {
      runtime: "browser-preview";
      href: string;
      openWindow: BrowserWindowOpener;
    };

export type ExternalLinkDispatchResult =
  | {
      status: "opened";
      via: "discord" | "browser";
      href: string;
    }
  | {
      status: "declined";
      via: "discord";
      href: string;
      reason: "discord-declined";
    }
  | {
      status: "failed";
      via: "discord" | "browser";
      href: string;
      reason:
        | "discord-not-ready"
        | "discord-command-failed"
        | "discord-invalid-response"
        | "popup-blocked";
    }
  | {
      status: "blocked";
      via: "policy";
      href: string | null;
      reason: "invalid-url" | "unsafe-protocol" | "credentials";
    };

function safeExternalHttpsHref(
  rawHref: string,
):
  | { ok: true; href: string }
  | {
      ok: false;
      href: string | null;
      reason: "invalid-url" | "unsafe-protocol" | "credentials";
    } {
  let destination: URL;
  try {
    destination = new URL(rawHref);
  } catch {
    return { ok: false, href: null, reason: "invalid-url" };
  }
  if (destination.username || destination.password) {
    return { ok: false, href: destination.href, reason: "credentials" };
  }
  if (destination.protocol !== "https:") {
    return {
      ok: false,
      href: destination.href,
      reason: "unsafe-protocol",
    };
  }
  return { ok: true, href: destination.href };
}

/**
 * Dispatches a previously classified external HTTPS link. Discord failures do
 * not fall back to window.open: awaiting the SDK command consumes the original
 * user gesture and Discord's Activity sandbox can reject the resulting popup.
 */
export async function dispatchActivityExternalLink(
  request: ExternalLinkDispatchRequest,
): Promise<ExternalLinkDispatchResult> {
  const safe = safeExternalHttpsHref(request.href);
  if (!safe.ok) {
    return {
      status: "blocked",
      via: "policy",
      href: safe.href,
      reason: safe.reason,
    };
  }

  if (request.runtime === "discord-activity") {
    if (!request.discordCommand) {
      return {
        status: "failed",
        via: "discord",
        href: safe.href,
        reason: "discord-not-ready",
      };
    }
    try {
      const response = await request.discordCommand.openExternalLink({
        url: safe.href,
      });
      if (
        !response ||
        (response.opened !== true &&
          response.opened !== false &&
          response.opened !== null)
      ) {
        return {
          status: "failed",
          via: "discord",
          href: safe.href,
          reason: "discord-invalid-response",
        };
      }
      if (response.opened === false) {
        return {
          status: "declined",
          via: "discord",
          href: safe.href,
          reason: "discord-declined",
        };
      }
      return { status: "opened", via: "discord", href: safe.href };
    } catch {
      return {
        status: "failed",
        via: "discord",
        href: safe.href,
        reason: "discord-command-failed",
      };
    }
  }

  const opened = request.openWindow(
    safe.href,
    "_blank",
    "noopener,noreferrer",
  );
  if (opened === null) {
    return {
      status: "failed",
      via: "browser",
      href: safe.href,
      reason: "popup-blocked",
    };
  }
  return { status: "opened", via: "browser", href: safe.href };
}
