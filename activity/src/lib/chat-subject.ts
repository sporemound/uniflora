interface SubjectMessage {
  requestId: string;
  senderType: "participant" | "hypha";
  text: string;
}

export function replySubject(messages: readonly SubjectMessage[], reply: SubjectMessage): string {
  const question = messages.find((item) =>
    item.requestId === reply.requestId && item.senderType === "participant");
  if (!question) return "Hypha reply";
  const words = question.text.replace(/\s+/gu, " ").trim();
  const limit = 64;
  const cut = words.lastIndexOf(" ", limit);
  const excerpt = words.length <= limit ? words :
    `${words.slice(0, cut >= 32 ? cut : limit).replace(/[,;:–-]$/u, "")}…`;
  return `Reply to “${excerpt}”`;
}
