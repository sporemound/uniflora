export type ActivityRoute =
  | {
      kind: "workspace";
      pathname: "/";
      search: string;
    }
  | {
      kind: "facilities";
      pathname: "/facilities";
      search: string;
    }
  | {
      kind: "facility";
      pathname: string;
      search: string;
      slug: string;
    }
  | {
      kind: "positions";
      pathname: "/positions";
      search: string;
    }
  | {
      kind: "cartography";
      pathname: "/cartography";
      search: string;
    }
  | {
      kind: "position";
      pathname: string;
      search: string;
      slug: string;
    }
  | {
      kind: "not-found";
      pathname: string;
      search: string;
    };

type RouteInput =
  | string
  | URL
  | Pick<Location, "pathname" | "search">;

type QuerySource =
  | string
  | URLSearchParams
  | Pick<ActivityRoute, "search">
  | Pick<Location, "search">
  | null
  | undefined;

function normalizeSearch(search: string): string {
  if (search === "" || search === "?") {
    return "";
  }
  return search.startsWith("?") ? search : `?${search}`;
}

function readRouteInput(input: RouteInput): {
  pathname: string;
  search: string;
} {
  if (typeof input !== "string") {
    return {
      pathname: input.pathname || "/",
      search: normalizeSearch(input.search),
    };
  }

  const parsed = new URL(input, "https://activity.invalid");
  return {
    pathname: parsed.pathname || "/",
    search: normalizeSearch(parsed.search),
  };
}

function routeSlug(pathname: string, prefix: string): string | null {
  if (!pathname.startsWith(`${prefix}/`)) {
    return null;
  }

  const encodedSlug = pathname.slice(prefix.length + 1);
  if (encodedSlug === "" || encodedSlug.includes("/")) {
    return null;
  }

  try {
    return decodeURIComponent(encodedSlug);
  } catch {
    return null;
  }
}

/**
 * Parses the small, server-fallback-safe route surface used by the Activity.
 * Unknown paths remain explicit so the UI can render an accessible 404 shell.
 */
export function parseActivityRoute(input: RouteInput): ActivityRoute {
  const { pathname, search } = readRouteInput(input);

  if (pathname === "/" || pathname === "") {
    return { kind: "workspace", pathname: "/", search };
  }
  if (pathname === "/facilities") {
    return { kind: "facilities", pathname, search };
  }
  if (pathname === "/positions") {
    return { kind: "positions", pathname, search };
  }
  if (pathname === "/cartography") {
    return { kind: "cartography", pathname, search };
  }

  const facilitySlug = routeSlug(pathname, "/facilities");
  if (facilitySlug !== null) {
    return {
      kind: "facility",
      pathname,
      search,
      slug: facilitySlug,
    };
  }

  const positionSlug = routeSlug(pathname, "/positions");
  if (positionSlug !== null) {
    return {
      kind: "position",
      pathname,
      search,
      slug: positionSlug,
    };
  }

  return { kind: "not-found", pathname, search };
}

function queryString(source: QuerySource): string {
  if (source === null || source === undefined) {
    return "";
  }
  if (typeof source === "string") {
    return normalizeSearch(source);
  }
  if (source instanceof URLSearchParams) {
    const value = source.toString();
    return value === "" ? "" : `?${value}`;
  }
  return normalizeSearch(source.search);
}

/**
 * Builds an internal Activity URL while retaining environment, room, and any
 * future query parameters from the current route.
 */
export function activityHref(
  pathname: string,
  query?: QuerySource,
): string {
  const parsed = new URL(pathname, "https://activity.invalid");
  const explicitQuery = parsed.search;
  const search = explicitQuery || queryString(query);
  return `${parsed.pathname}${search}${parsed.hash}`;
}
