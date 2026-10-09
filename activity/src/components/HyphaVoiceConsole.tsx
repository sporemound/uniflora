import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { audioController } from "../lib/audio-controller";
import { replySubject } from "../lib/chat-subject";
import { siteAuthHeaders, type SiteConnectionState } from "../lib/site-auth";
import type { SnapshotOrigin } from "../lib/api";
import type { EnvironmentName, PublicActivitySnapshot } from "../shared/public-state";
import { GuestHyphaDemo } from "./GuestHyphaDemo";
import "./HyphaVoiceConsole.css";

interface HyphaVoiceConsoleProps {
  sessionToken: string | null;
  connectionStatus: SiteConnectionState["status"];
  connectionDetail: string;
  workingName: string;
  environment: EnvironmentName;
  snapshot: PublicActivitySnapshot;
  guidanceMode: GuidanceMode;
  previewOnly?: boolean;
  snapshotOrigin?: SnapshotOrigin;
  previewReadiness?: {
    status: "checking" | "ready" | "error";
    emailReady: boolean;
    chatReadReady: boolean;
    chatReady: boolean;
    demoReady: boolean;
    gameActionsReady: boolean;
  };
}

export type GuidanceMode = "guided" | "standard" | "expert";

const ALBUQUERQUE_MODE_STORAGE_KEY = "the-missing-interior.albuquerque-mode";

function savedAlbuquerqueMode(): boolean {
  try {
    return window.localStorage.getItem(ALBUQUERQUE_MODE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

interface ChatMessage {
  messageId: string;
  requestId: string;
  environment: EnvironmentName;
  streamId: string;
  senderType: "participant" | "hypha";
  participantId: string | null;
  workingName: string | null;
  text: string;
  status: "pending" | "processing" | "complete" | "failed";
  audioUrl: string | null;
  createdAt: number;
  completedAt: number | null;
}

interface ChatPage {
  environment: EnvironmentName;
  streamId: string;
  messages: ChatMessage[];
  hasMore: boolean;
}

function bearer(sessionToken: string): HeadersInit {
  return {
    Accept: "application/json",
    ...siteAuthHeaders(sessionToken),
  };
}

function mergeMessages(
  previous: ChatMessage[],
  incoming: ChatMessage[],
  older = false,
): ChatMessage[] {
  const ids = new Set(incoming.map((item) => item.messageId));
  const remainder = previous.filter((item) => !ids.has(item.messageId));
  return older ? [...incoming, ...remainder] : [...remainder, ...incoming];
}

function displayTime(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function HyphaVoiceConsole({
  sessionToken,
  connectionStatus,
  connectionDetail,
  workingName,
  environment,
  snapshot,
  guidanceMode,
  previewOnly = false,
  snapshotOrigin = "unavailable",
  previewReadiness,
}: HyphaVoiceConsoleProps) {
  const publishedPreview = previewOnly && snapshotOrigin === "published";
  const gameActionsReady = previewReadiness?.gameActionsReady === true;
  const nextStep = previewOnly && !publishedPreview
    ? "Choose one permanent investigative role when game participation opens."
    : snapshot.nextRequirement;
  const chatEnabled = (import.meta.env.VITE_ENABLE_LIVE_CHAT === "true" ||
    (!previewOnly && environment === "test")) &&
    (!previewOnly || previewReadiness?.chatReadReady === true);
  const [message, setMessage] = useState("");
  const [albuquerqueMode, setAlbuquerqueMode] = useState(savedAlbuquerqueMode);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamId, setStreamId] = useState<string | null>(null);
  const [serverReady, setServerReady] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [sending, setSending] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [detail, setDetail] = useState("Shared investigation channel is ready.");
  const messagesRef = useRef<ChatMessage[]>([]);
  const loadedAllOlderRef = useRef(false);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    try {
      window.localStorage.setItem(ALBUQUERQUE_MODE_STORAGE_KEY, albuquerqueMode ? "1" : "0");
    } catch {
      // Chat still works when browser storage is unavailable.
    }
  }, [albuquerqueMode]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!chatEnabled || (!previewOnly && !sessionToken) || document.hidden) return;
    const latest = messagesRef.current.at(-1);
    const url = latest
      ? `/api/hypha-chat?limit=50&after=${encodeURIComponent(latest.messageId)}`
      : "/api/hypha-chat?limit=50";
    const response = await fetch(url, {
      headers: sessionToken ? bearer(sessionToken) : { Accept: "application/json" },
      signal,
    });
    if (!response.ok) throw new Error(`Shared chat unavailable (${response.status}).`);
    const page = (await response.json()) as ChatPage;
    if (page.environment !== environment) throw new Error("Chat session does not match this campaign.");
    if (signal?.aborted) return;
    setServerReady(true);
    setDetail("Shared investigation channel is ready.");
    setStreamId(page.streamId);
    setMessages((previous) => mergeMessages(previous, page.messages));
    if (!latest && !loadedAllOlderRef.current) setHasMore(page.hasMore);
  }, [chatEnabled, environment, previewOnly, sessionToken]);

  useEffect(() => {
    messagesRef.current = [];
    setMessages([]);
    setStreamId(null);
    setServerReady(false);
    setHasMore(false);
    loadedAllOlderRef.current = false;
    if (!chatEnabled) {
      setDetail(previewOnly
        ? previewReadiness?.status === "checking"
          ? "Checking Hypha chat availability…"
          : previewReadiness?.status === "error"
            ? "Could not check Hypha chat availability. Reload the page to retry."
            : "Hypha chat history is still being configured for this preview."
        : "Shared Hypha conversation is not enabled for this live campaign.");
      return;
    }
    setDetail("Connecting to the shared investigation channel…");
    if (!sessionToken && !previewOnly) return;
    let active = true;
    const pending = new Set<AbortController>();
    const poll = () => {
      const controller = new AbortController();
      pending.add(controller);
      void refresh(controller.signal)
        .catch((error: unknown) => {
          if (active) {
            setServerReady(false);
            setDetail(error instanceof Error && error.message.includes("503")
              ? "Hypha chat is temporarily unavailable. Please try again shortly."
              : error instanceof Error ? error.message : "Shared chat unavailable.");
          }
        })
        .finally(() => pending.delete(controller));
    };
    poll();
    const timer = window.setInterval(poll, previewOnly && !sessionToken ? 10_000 : 5000);
    window.addEventListener("focus", poll);
    document.addEventListener("visibilitychange", poll);
    return () => {
      active = false;
      for (const controller of pending) controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", poll);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [chatEnabled, environment, previewOnly, previewReadiness?.status, refresh, sessionToken]);

  const loadOlder = async () => {
    const oldest = messagesRef.current[0];
    if ((!sessionToken && !previewOnly) || !oldest || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const response = await fetch(
        `/api/hypha-chat?limit=50&before=${encodeURIComponent(oldest.messageId)}`,
        { headers: sessionToken ? bearer(sessionToken) : { Accept: "application/json" } },
      );
      if (!response.ok) throw new Error(`Older chat unavailable (${response.status}).`);
      const page = (await response.json()) as ChatPage;
      setMessages((previous) => mergeMessages(previous, page.messages, true));
      setHasMore(page.hasMore);
      loadedAllOlderRef.current = !page.hasMore;
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "Older chat unavailable.");
    } finally {
      setLoadingOlder(false);
    }
  };

  const play = useCallback(async (item: ChatMessage) => {
    if (!sessionToken || !item.audioUrl || !item.text.trim()) return;
    setPlayingId(item.messageId);
    try {
      if (!audioController.getSnapshot().enabled) {
        await audioController.enable();
      }
      const response = await fetch(item.audioUrl, {
        headers: bearer(sessionToken),
      });
      if (!response.ok) throw new Error(`Hypha audio unavailable (${response.status}).`);
      const played = await audioController.playPresentationAudio(
        await response.arrayBuffer(), item.text,
      );
      setDetail(played
        ? "Hypha is speaking."
        : "Enable and unmute site audio to hear Hypha; the transcript is available below.");
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "Hypha audio unavailable.");
    } finally {
      setPlayingId(null);
    }
  }, [sessionToken]);

  const submitQuestion = async (question: string, clearDraft = false) => {
    const normalized = question.trim();
    if (!sessionToken || !normalized || sending) return;
    setSending(true);
    setDetail("Sending your question to the shared investigation channel…");
    try {
      const response = await fetch("/api/hypha-chat", {
        method: "POST",
        headers: { ...bearer(sessionToken), "Content-Type": "application/json" },
        body: JSON.stringify({ environment, streamId, message: normalized, albuquerqueMode,
          ...(workingName ? { workingName } : {}) }),
      });
      if (!response.ok) throw new Error(`Hypha request rejected (${response.status}).`);
      const created = (await response.json()) as {
        requestId: string;
        messages: ChatMessage[];
      };
      setMessages((previous) => mergeMessages(previous, created.messages));
      if (clearDraft) setMessage("");
      setDetail(created.messages.some((item) => item.senderType === "hypha" && item.status === "complete")
        ? "Hypha's reply is in the chat below."
        : "Your message was sent. Hypha is preparing a response.");
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "Hypha request failed.");
    } finally {
      setSending(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitQuestion(message, true);
  };

  const publicV2 = snapshot.schemaVersion === "2.3.0" ||
    snapshot.schemaVersion === "2.4.0" ? snapshot : null;
  const nextEvidence = publicV2?.evidence.find((item) => item.status === "available");
  const nextAction = publicV2?.actions.find((item) => item.status === "available");
  const historyReady = Boolean(chatEnabled && serverReady);
  const chatReady = Boolean(historyReady && sessionToken &&
    (!previewOnly || previewReadiness?.chatReady));

  return (
    <section className="hypha-voice-console" id="hypha-chat" aria-labelledby="hypha-voice-heading">
      <div className="hypha-voice-console__heading">
        <div>
          <p className="eyebrow">Investigation guidance</p>
          <h2 id="hypha-voice-heading">Chat with Hypha</h2>
        </div>
        <span>{previewOnly
          ? snapshotOrigin === "published" ? "Live public record"
            : snapshotOrigin === "archived" ? "Captured case archive"
              : "Public case preview"
          : environment === "test" ? "Private test stream" : "Live investigation"}</span>
      </div>

      {guidanceMode === "guided" ? (
        <aside className="hypha-voice-console__guidance" aria-label="Guided investigation help">
          <h3>Your next step</h3>
          <p>{nextStep}</p>
          {nextEvidence ? <p><strong>Evidence ready:</strong> {nextEvidence.name}. Ask Hypha to explain what it shows{previewOnly && !gameActionsReady ? "." : ", or follow the published command."}</p> : null}
          {nextAction && (!previewOnly || publishedPreview) ? <p><strong>Public action:</strong> {nextAction.title}. {nextAction.description}{nextAction.requiredRoleIds.length ? ` Requires a role: ${nextAction.requiredRoleIds.join(", ")}.` : ""}{previewOnly && !gameActionsReady ? " Game commands are being connected." : ""}</p> : null}
          {chatEnabled ? <p>{sessionToken
            ? "Ask Hypha below for an explanation. Its reply appears as text here."
            : previewOnly
              ? "Try a guest question below. Sign in by email to post in the public chat."
              : "Read the public Hypha conversation below. Sign in by email to ask a question."}</p> : null}
        </aside>
      ) : guidanceMode === "standard" ? (
        <p className="hypha-voice-console__next-step"><strong>Next step:</strong> {nextStep}</p>
      ) : null}

      <div className="hypha-voice-console__mode">
        <div>
          <strong>Reply style</strong>
          <p id="hypha-albuquerque-description">Adds “Albuquerque” after every vowel in new Hypha replies. Earlier messages stay as written.</p>
        </div>
        <button type="button" aria-label="Albuquerque Mode" aria-pressed={albuquerqueMode}
          aria-describedby="hypha-albuquerque-description"
          onClick={() => setAlbuquerqueMode((enabled) => !enabled)}>
          Albuquerque Mode: <span aria-hidden="true">{albuquerqueMode ? "On" : "Off"}</span>
        </button>
      </div>

      {previewOnly && !sessionToken ? (
        <GuestHyphaDemo
          albuquerqueMode={albuquerqueMode}
          ready={previewReadiness?.demoReady === true}
          readinessStatus={previewReadiness?.status ?? "checking"}
        />
      ) : null}

      {!historyReady ? (
        <div className="hypha-voice-console__connection" role={connectionStatus === "error" && !previewOnly ? "alert" : "status"}>
          <strong>{!chatEnabled ? previewOnly ? "Chat setup pending" : "Hypha conversation unavailable" :
            previewOnly ? "Loading public chat" :
            connectionStatus === "error" ? "Connection failed" :
            connectionStatus === "signed-out" ? "Sign in to use shared chat" :
              "Connecting to shared chat"}</strong>
          <p>{!chatEnabled || previewOnly ? detail :
            connectionStatus === "error" || connectionStatus === "signed-out" ? connectionDetail : detail}</p>
          {chatEnabled && connectionStatus === "signed-out" && !previewOnly ? <p>Use the email form above to request a sign-in link.</p> : null}
        </div>
      ) : previewOnly && !sessionToken ? (
        <div className="hypha-voice-console__connection" role="status">
          <strong>Public chat log</strong>
          <p>Anyone with this website link can read the shared chat. Sign in by email to post.</p>
        </div>
      ) : previewOnly && !chatReady ? (
        <div className="hypha-voice-console__connection" role="status">
          <strong>Posting unavailable</strong>
          <p>You can read the shared chat while Hypha replies are being configured.</p>
        </div>
      ) : null}
      {chatEnabled ? <>
          {guidanceMode !== "expert" && (sessionToken || !previewOnly) ? (
            <div className="hypha-voice-console__quick-questions" aria-label="Ask Hypha for guidance">
              <button type="button" disabled={!chatReady || sending || !streamId}
                onClick={() => void submitQuestion(previewOnly && !publishedPreview
                  ? "Summarize the captured public case and the evidence I can examine in this preview."
                  : "Guide me through the immediate next step. Explain why it matters, any role I need, and the exact command I should use if one is published.",
                )}>
                {previewOnly && !publishedPreview ? "Summarize case" : "Explain next step"}
              </button>
              {guidanceMode === "guided" && (!previewOnly || gameActionsReady) ? (
                <>
                  <button type="button" disabled={!chatReady || sending || !streamId}
                    onClick={() => void submitQuestion(
                      "What public commands can I use now, and what does each one do? Include prerequisites and exact command text.",
                    )}>
                    Explain commands
                  </button>
                  <button type="button" disabled={!chatReady || sending || !streamId}
                    onClick={() => void submitQuestion(
                      "Which permanent investigative roles can I choose now, and how do I select one? Explain the role choices before I commit.",
                    )}>
                    Explain roles
                  </button>
                </>
              ) : null}
            </div>
          ) : null}
          <div className="hypha-voice-console__history" role="log" aria-label="Shared Hypha chat history">
            {hasMore ? (
              <button type="button" onClick={() => void loadOlder()} disabled={loadingOlder}>
                {loadingOlder ? "Loading…" : "Load earlier messages"}
              </button>
            ) : null}
            {messages.length === 0 ? <p>{historyReady ? "No messages yet in this investigation." : "Loading shared chat history…"}</p> : null}
            {messages.map((item) => (
              <article className="hypha-voice-console__entry" data-sender={item.senderType} key={item.messageId}>
                <header>
                  <div className="hypha-voice-console__entry-heading">
                    <strong>{item.senderType === "hypha" ? "Hypha" : item.workingName || "Investigator"}</strong>
                    {item.senderType === "hypha" ? (
                      <span>{replySubject(messages, item)}</span>
                    ) : null}
                  </div>
                  <time dateTime={new Date(item.createdAt * 1000).toISOString()}>
                    {displayTime(item.createdAt)}
                  </time>
                </header>
                {item.senderType === "participant" ? <p>{item.text}</p> : item.status === "pending" || item.status === "processing" ? (
                  <p className="hypha-voice-console__pending">Preparing Hypha's reply…</p>
                ) : (
                  <div className="hypha-voice-console__response">
                    <p>{item.text}</p>
                    {item.audioUrl ? (
                      <button type="button" onClick={() => void play(item)} disabled={playingId === item.messageId}>
                        {playingId === item.messageId ? "Opening audio…" : "▶ Play reply"}
                      </button>
                    ) : null}
                  </div>
                )}
              </article>
            ))}
          </div>
          {previewOnly ? <p className="hypha-voice-console__fallback">
            Anyone with this website link can read the shared chat, including your displayed name and message.
            New messages and recent shared chat are sent to Google Gemini for Hypha's replies. Do not include private information.
          </p> : null}
          {previewOnly && !sessionToken ? <p className="hypha-voice-console__fallback">
            Sign in with the email form above to post in the shared chat.
          </p> : <form onSubmit={submit}>
            <label htmlFor="hypha-question">Message or question for the shared investigation</label>
            <div className="hypha-voice-console__input-row">
              <textarea id="hypha-question" value={message} maxLength={4000} rows={2}
                placeholder="Ask about the current record, contradictions, or procedures…"
                onChange={(event) => setMessage(event.currentTarget.value)} disabled={!chatReady || sending} />
              <button type="submit" disabled={!chatReady || !message.trim() || sending || !streamId}>
                {sending ? "Sending…" : "Send message"}
              </button>
            </div>
          </form>}
          <p className="hypha-voice-console__fallback">
            Replies appear as text. Audio is optional when available.
          </p>
      </> : null}
      <p className="hypha-voice-console__status" role="status" aria-live="polite">
        {!sessionToken && chatEnabled && !previewOnly ? connectionDetail : detail}
      </p>
    </section>
  );
}
