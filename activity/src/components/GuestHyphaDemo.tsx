import { useState, type FormEvent } from "react";
import "./GuestHyphaDemo.css";

interface GuestHyphaDemoProps {
  albuquerqueMode: boolean;
  ready: boolean;
  readinessStatus: "checking" | "ready" | "error";
}

interface DemoExchange {
  question: string;
  reply: string;
}

const MAX_QUESTIONS = 3;
const MAX_MESSAGE_LENGTH = 500;

function unavailableText(status: GuestHyphaDemoProps["readinessStatus"]): string {
  if (status === "checking") return "Checking guest demo availability…";
  if (status === "error") return "Could not check the guest demo. Reload the page to retry.";
  return "The guest demo is temporarily unavailable. Please try again later.";
}

async function responseError(response: Response): Promise<string> {
  if (response.status === 429) return "The guest demo limit was reached. Wait a minute and try again.";
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "message" in body &&
      typeof body.message === "string" && body.message.trim()) {
      return body.message;
    }
  } catch {
    // A failed or non-JSON response still gets a useful message.
  }
  if (response.status === 503) return "The guest demo is temporarily unavailable. No exchange was posted.";
  return `Hypha could not answer this question (${response.status}).`;
}

export function GuestHyphaDemo({
  albuquerqueMode,
  ready,
  readinessStatus,
}: GuestHyphaDemoProps) {
  const [draft, setDraft] = useState("");
  const [exchanges, setExchanges] = useState<DemoExchange[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const remaining = MAX_QUESTIONS - exchanges.length;
  const canSend = ready && !sending && remaining > 0;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const question = draft.trim();
    if (!canSend || !question || question.length > MAX_MESSAGE_LENGTH) return;
    setSending(true);
    setError("");
    try {
      const response = await fetch("/api/hypha-demo", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        credentials: "omit",
        cache: "no-store",
        body: JSON.stringify({ message: question, albuquerqueMode }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result: unknown = await response.json();
      if (!result || typeof result !== "object" || !("reply" in result) ||
        typeof result.reply !== "string" || !result.reply.trim()) {
        throw new Error("Hypha returned an empty reply. Please try again.");
      }
      const reply = result.reply;
      setExchanges((current) => [...current, { question, reply }]);
      setDraft("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Hypha could not answer. Please try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="guest-hypha-demo" aria-labelledby="guest-hypha-heading">
      <div className="guest-hypha-demo__heading">
        <div>
          <p className="eyebrow">No sign-in needed</p>
          <h3 id="guest-hypha-heading">Try Hypha</h3>
        </div>
        <span>Guest demo</span>
      </div>
      <p className="guest-hypha-demo__intro">
        Ask up to three short questions about the public case. Each question stands alone; Hypha does not remember earlier demo questions.
      </p>
      <p className="guest-hypha-demo__privacy">
        Your question and Hypha&apos;s reply are saved in the public chat log and can be read by anyone with this website link, even after you leave. Do not include personal information.
        Your question is also sent to Google Gemini, which may use free-tier requests to improve its products.
      </p>
      {exchanges.length > 0 ? (
        <div className="guest-hypha-demo__history" role="log" aria-label="Guest demo replies" aria-live="polite">
          {exchanges.map((exchange, index) => (
            <div className="guest-hypha-demo__exchange" key={index}>
              <p><strong>You:</strong> {exchange.question}</p>
              <p><strong>Hypha:</strong> {exchange.reply}</p>
            </div>
          ))}
        </div>
      ) : null}
      {!ready ? <p className="guest-hypha-demo__availability" role="status">{unavailableText(readinessStatus)}</p> : null}
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor="guest-hypha-question">Your demo question</label>
        <div className="hypha-voice-console__input-row">
          <textarea
            id="guest-hypha-question"
            value={draft}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={2}
            placeholder="What does the public evidence suggest?"
            onChange={(event) => setDraft(event.currentTarget.value)}
            disabled={!canSend}
          />
          <button type="submit" disabled={!canSend || !draft.trim()}>
            {sending ? "Asking…" : "Ask Hypha"}
          </button>
        </div>
      </form>
      {ready ? <p className="guest-hypha-demo__remaining" role="status">
        {remaining > 0 ? `${remaining} demo ${remaining === 1 ? "question" : "questions"} left on this page.` :
          "Guest demo complete for this page."}
      </p> : null}
      {error ? <p className="guest-hypha-demo__error" role="alert">{error}</p> : null}
    </section>
  );
}
