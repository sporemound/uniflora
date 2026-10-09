import "./CampaignEmblem.css";

export function CampaignEmblem() {
  return (
    <figure className="campaign-emblem">
      <div className="campaign-emblem__art">
        <img
          src="/uniflora-emblem.png"
          alt="A bowed flower above branching roots, framed by an ornate woven border"
          width={1920}
          height={1080}
        />
      </div>
      <figcaption className="campaign-emblem__caption">
        <span className="campaign-emblem__label">The Missing Interior / campaign emblem</span>
        <strong>Uniflora</strong>
      </figcaption>
    </figure>
  );
}
