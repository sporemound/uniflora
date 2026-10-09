import { ViewportInfoPopover } from "./ViewportInfoPopover";

interface MetricCardProps {
  label: string;
  value: number;
  note: string;
  definition: string;
}

export function MetricCard({
  label,
  value,
  note,
  definition,
}: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className="metric-card-heading">
        <p className="metric-label">{label}</p>
        <ViewportInfoPopover
          title={label}
          ariaLabel={`Explain the ${label.toLocaleLowerCase()} value`}
          triggerText="Info"
          triggerVariant="tab"
        >
          <small>{definition}</small>
          <em>Displayed as an unscored public-state count.</em>
        </ViewportInfoPopover>
      </div>
      <p className="metric-value">{value}</p>
      <p className="metric-note">{note}</p>
    </article>
  );
}
