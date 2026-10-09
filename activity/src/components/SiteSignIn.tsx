import { useState, type FormEvent } from "react";
import { requestMagicLink } from "../lib/site-auth";

interface SiteSignInProps {
  previewOnly?: boolean;
  chatReadReady?: boolean;
  chatReady?: boolean;
  gameActionsReady?: boolean;
  emailReadiness?: "checking" | "ready" | "pending" | "error";
  onRetryReadiness?: () => void;
}

export function SiteSignIn({ previewOnly = false, chatReadReady = false, chatReady = true,
  gameActionsReady = false,
  emailReadiness = "ready", onRetryReadiness }: SiteSignInProps) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [detail, setDetail] = useState("");
  const roleStatus = gameActionsReady
    ? "After sign-in, choose one permanent investigative role."
    : "Permanent role selection opens when game participation begins.";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "sending") return;
    setStatus("sending");
    try {
      await requestMagicLink(email.trim());
      setStatus("sent");
      setDetail("If that address can receive mail, a sign-in link is on its way.");
    } catch (error) {
      setStatus("error");
      setDetail(error instanceof Error ? error.message : "Could not request a sign-in link.");
    }
  }

  return (
    <section className="site-sign-in" aria-labelledby="site-sign-in-heading">
      <div>
        <p className="eyebrow">Join the investigation</p>
        <h2 id="site-sign-in-heading">Sign in with a link</h2>
        <p>{previewOnly
          ? chatReadReady
            ? emailReadiness === "ready" && chatReady
              ? `Anyone with this link can read the shared chat. Enter your email and open the link we send you to post. ${roleStatus}`
              : `Anyone with this link can read the shared chat. Email sign-in for posting is still being configured. ${roleStatus}`
            : emailReadiness === "ready"
            ? chatReady
              ? `Enter your email and open the link we send you to chat with Hypha. ${roleStatus}`
              : `Enter your email to register for the investigation. Hypha chat is still being configured. ${roleStatus}`
            : `Public chat history is being prepared. Email sign-in will be required to post when it opens. ${roleStatus}`
          : "Enter your email and open the link we send you. Your account and role will follow you through the campaign."}</p>
      </div>
      {emailReadiness === "checking" ? <p role="status">Checking email sign-in availability…</p> : null}
      {emailReadiness === "pending" ? (
        <p role="status">Email sign-in is still being configured for this preview. Posting will open after it is connected.</p>
      ) : null}
      {emailReadiness === "error" ? (
        <div>
          <p role="alert">Could not check email sign-in availability.</p>
          <button type="button" onClick={onRetryReadiness}>Retry check</button>
        </div>
      ) : null}
      {emailReadiness === "ready" ? <form onSubmit={(event) => void submit(event)}>
        <label htmlFor="site-sign-in-email">Email address</label>
        <div className="site-sign-in__controls">
          <input
            id="site-sign-in-email"
            type="email"
            autoComplete="email"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={status === "sending"}
          />
          <button type="submit" disabled={status === "sending"}>
            {status === "sending" ? "Sending…" : "Email me a link"}
          </button>
        </div>
        {detail ? <p role={status === "error" ? "alert" : "status"}>{detail}</p> : null}
      </form> : null}
    </section>
  );
}
