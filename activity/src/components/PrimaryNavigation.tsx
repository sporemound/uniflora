import { activityHref, type ActivityRoute } from "../lib/routes";

interface PrimaryNavigationProps {
  route: ActivityRoute;
}

const PRIMARY_DESTINATIONS = [
  {
    kind: "workspace",
    href: "/",
    label: "Workspace",
    detail: "Evidence and review",
  },
  {
    kind: "facilities",
    href: "/facilities",
    label: "Facilities",
    detail: "Access consoles",
  },
  {
    kind: "positions",
    href: "/positions",
    label: "Positions",
    detail: "Investigation state",
  },
  {
    kind: "cartography",
    href: "/cartography",
    label: "Cartography",
    detail: "Full map",
  },
] as const;

function activeDestination(
  route: ActivityRoute,
): (typeof PRIMARY_DESTINATIONS)[number]["kind"] | null {
  if (route.kind === "facility") {
    return "facilities";
  }
  if (route.kind === "position") {
    return "positions";
  }
  if (
    route.kind === "workspace" ||
    route.kind === "facilities" ||
    route.kind === "positions" ||
    route.kind === "cartography"
  ) {
    return route.kind;
  }
  return null;
}

export function PrimaryNavigation({ route }: PrimaryNavigationProps) {
  const active = activeDestination(route);

  return (
    <nav className="primary-navigation" aria-label="Primary">
      <a
        className="primary-navigation-brand"
        href={activityHref("/", route)}
        aria-label="The Missing Interior workspace"
      >
        <span aria-hidden="true" className="primary-navigation-orbit">
          <i />
        </span>
        <span>
          <strong>The Missing Interior</strong>
          <small>Public investigation access</small>
        </span>
      </a>

      <ul>
        {PRIMARY_DESTINATIONS.map((destination) => (
          <li key={destination.kind}>
            <a
              href={activityHref(destination.href, route)}
              aria-current={active === destination.kind ? "page" : undefined}
            >
              <span>{destination.label}</span>
              <small>{destination.detail}</small>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
