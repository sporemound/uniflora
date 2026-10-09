import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { transformWithOxc } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = path.join(root, "src", "lib", "activity-link-navigation.ts");
const source = await readFile(sourcePath, "utf8");
const appSource = await readFile(path.join(root, "src", "App.tsx"), "utf8");
const discordSource = await readFile(path.join(root, "src", "lib", "discord.ts"), "utf8");
const mapSource = await readFile(
  path.join(root, "src", "components", "GeographicFieldMap.tsx"),
  "utf8",
);
const scienceSource = await readFile(
  path.join(root, "src", "components", "FacilityScienceLab.tsx"),
  "utf8",
);
const javascript = (await transformWithOxc(source, sourcePath)).code;
const {
  classifyActivityLink,
  dispatchActivityExternalLink,
} = await import(
  `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`
);

const currentHref = "https://activity.example.test/?environment=test";

assert.deepEqual(
  classifyActivityLink({
    currentHref,
    href: "/cartography?environment=test&sidequest=ufosint%3A12#cartography-content",
    runtime: "discord-activity",
  }),
  {
    intent: "internal",
    href:
      "https://activity.example.test/cartography?environment=test&sidequest=ufosint%3A12#cartography-content",
    historyHref:
      "/cartography?environment=test&sidequest=ufosint%3A12#cartography-content",
    fragment: "cartography-content",
  },
  "same-origin routes must preserve their query and fragment for SPA navigation",
);

assert.deepEqual(
  classifyActivityLink({
    currentHref: "https://activity.example.test/cartography?environment=test",
    href: "/#overview",
    runtime: "discord-activity",
    target: "_self",
  }),
  {
    intent: "internal",
    href: "https://activity.example.test/#overview",
    historyHref: "/#overview",
    fragment: "overview",
  },
  "internal fragment navigation must remain explicit",
);

assert.equal(
  classifyActivityLink({
    currentHref,
    href: "/facilities/boundary-array",
    runtime: "discord-activity",
    target: "_blank",
  }).intent,
  "internal",
  "Discord must keep same-origin target=_blank links inside the SPA",
);

const discordExternal = classifyActivityLink({
  currentHref,
  href: "https://dynamical.org/catalog/noaa-gfs-analysis/",
  runtime: "discord-activity",
  target: "_blank",
});
assert.deepEqual(
  discordExternal,
  {
    intent: "discord-external",
    href: "https://dynamical.org/catalog/noaa-gfs-analysis/",
  },
  "Discord must intercept target=_blank HTTPS links",
);

assert.deepEqual(
  classifyActivityLink({
    currentHref,
    href: "https://dynamical.org/catalog/noaa-gfs-analysis/",
    runtime: "browser-preview",
    target: "_blank",
  }),
  {
    intent: "browser-default",
    href: "https://dynamical.org/catalog/noaa-gfs-analysis/",
    external: true,
  },
  "ordinary browser previews must retain native external-link behavior",
);

for (const [field, value, reason] of [
  ["defaultPrevented", true, "default-prevented"],
  ["button", 1, "non-primary"],
  ["metaKey", true, "modifier"],
  ["ctrlKey", true, "modifier"],
  ["shiftKey", true, "modifier"],
  ["altKey", true, "modifier"],
  ["download", true, "download"],
]) {
  assert.deepEqual(
    classifyActivityLink({
      currentHref,
      href: "/cartography",
      runtime: "discord-activity",
      [field]: value,
    }),
    { intent: "ignore", reason },
    `${field} activations must not be intercepted`,
  );
}

for (const [href, reason] of [
  ["http://example.test/report", "unsafe-protocol"],
  ["javascript:alert(1)", "unsafe-protocol"],
  ["data:text/plain,report", "unsafe-protocol"],
  ["https://alice:secret@example.test/report", "credentials"],
]) {
  const decision = classifyActivityLink({
    currentHref,
    href,
    runtime: "discord-activity",
  });
  assert.equal(decision.intent, "blocked", `${href} must be blocked`);
  assert.equal(decision.reason, reason, `${href} has the expected block reason`);
}

const malformed = classifyActivityLink({
  currentHref: "not a current URL",
  href: "relative",
  runtime: "discord-activity",
});
assert.deepEqual(
  malformed,
  { intent: "blocked", href: null, reason: "invalid-url" },
  "malformed URL context must fail closed",
);

async function discordDispatch(opened) {
  const calls = [];
  const result = await dispatchActivityExternalLink({
    runtime: "discord-activity",
    href: "https://example.test/report path",
    discordCommand: {
      async openExternalLink(input) {
        calls.push(input);
        return { opened };
      },
    },
  });
  return { calls, result };
}

for (const opened of [true, null]) {
  const dispatch = await discordDispatch(opened);
  assert.deepEqual(dispatch.calls, [
    { url: "https://example.test/report%20path" },
  ]);
  assert.deepEqual(dispatch.result, {
    status: "opened",
    via: "discord",
    href: "https://example.test/report%20path",
  });
}

const declined = await discordDispatch(false);
assert.deepEqual(declined.result, {
  status: "declined",
  via: "discord",
  href: "https://example.test/report%20path",
  reason: "discord-declined",
});

let sandboxFallbackCalls = 0;
const thrown = await dispatchActivityExternalLink({
  runtime: "discord-activity",
  href: "https://example.test/report",
  discordCommand: {
    async openExternalLink() {
      throw new Error("Discord command unavailable");
    },
  },
  openWindow() {
    sandboxFallbackCalls += 1;
    return {};
  },
});
assert.deepEqual(thrown, {
  status: "failed",
  via: "discord",
  href: "https://example.test/report",
  reason: "discord-command-failed",
});

const notReady = await dispatchActivityExternalLink({
  runtime: "discord-activity",
  href: "https://example.test/report",
  discordCommand: null,
  openWindow() {
    sandboxFallbackCalls += 1;
    return {};
  },
});
assert.deepEqual(notReady, {
  status: "failed",
  via: "discord",
  href: "https://example.test/report",
  reason: "discord-not-ready",
});
assert.equal(
  sandboxFallbackCalls,
  0,
  "Discord command failures must not attempt a sandboxed popup fallback",
);

const invalidResponse = await dispatchActivityExternalLink({
  runtime: "discord-activity",
  href: "https://example.test/report",
  discordCommand: {
    async openExternalLink() {
      return {};
    },
  },
});
assert.deepEqual(invalidResponse, {
  status: "failed",
  via: "discord",
  href: "https://example.test/report",
  reason: "discord-invalid-response",
});

const popupCalls = [];
const browserOpened = await dispatchActivityExternalLink({
  runtime: "browser-preview",
  href: "https://example.test/report",
  openWindow(...args) {
    popupCalls.push(args);
    return {};
  },
});
assert.deepEqual(popupCalls, [
  ["https://example.test/report", "_blank", "noopener,noreferrer"],
]);
assert.deepEqual(browserOpened, {
  status: "opened",
  via: "browser",
  href: "https://example.test/report",
});

const popupBlocked = await dispatchActivityExternalLink({
  runtime: "browser-preview",
  href: "https://example.test/report",
  openWindow() {
    return null;
  },
});
assert.deepEqual(popupBlocked, {
  status: "failed",
  via: "browser",
  href: "https://example.test/report",
  reason: "popup-blocked",
});

let unsafeDispatchCalls = 0;
const unsafeDispatch = await dispatchActivityExternalLink({
  runtime: "browser-preview",
  href: "http://example.test/report",
  openWindow() {
    unsafeDispatchCalls += 1;
    return {};
  },
});
assert.deepEqual(unsafeDispatch, {
  status: "blocked",
  via: "policy",
  href: "http://example.test/report",
  reason: "unsafe-protocol",
});
assert.equal(unsafeDispatchCalls, 0, "blocked URLs must never reach a dispatcher");

assert.match(
  appSource,
  /document\.addEventListener\("click", navigateWithinActivity, true\)/u,
  "Activity links must be intercepted in capture phase before MapLibre can stop bubbling",
);
assert.match(appSource, /classifyActivityLink\(/u, "App must use the shared link policy");
assert.match(appSource, /runtime: "browser-preview"/u,
  "The standalone domain must use browser navigation");
assert.ok(!appSource.includes('from "./lib/discord"') &&
  !mapSource.includes('from "../lib/discord"'),
"The domain entry points must not load the Discord SDK");
assert.match(
  appSource,
  /const next = new URL\(current\.href\)/u,
  "custom-ID routing must preserve existing query parameters",
);
assert.ok(
  discordSource.indexOf("readyDiscordSdk = sdk") <
    discordSource.indexOf("sdk.commands.authorize"),
  "external-link SDK readiness must not depend on OAuth",
);
assert.ok(
  !mapSource.includes("handleExternalLink") &&
    !scienceSource.includes("openExternalActivityLink"),
  "component-specific external handlers must not duplicate central dispatch",
);

console.log(
  JSON.stringify(
    {
      ok: true,
      validator: "activity-links",
      classifierCases: 17,
      dispatchCases: 9,
      integrationChecks: 7,
      sandboxFallbacks: sandboxFallbackCalls,
    },
    null,
    2,
  ),
);
