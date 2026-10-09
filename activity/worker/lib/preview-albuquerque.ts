/** Deterministic, single-pass Albuquerque rendering for a Gemini reply. */
const INSERTION = "Albuquerque";
const VOWEL = /[aeiou]/iu;
const FENCE = /^[ ]{0,3}(?:>[ ]{0,3})*(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)?[ ]{0,3}(`{3,}|~{3,})/u;
const LINK_DEFINITION = /^[ ]{0,3}\[[^\]\n]+\]:[ \t]*\S/u;
const PROTECTED = /^(?:https?:\/\/|ftp:\/\/|file:\/\/|mailto:|www\.)[^\s<>"']*|^[A-Za-z]:[\\/][^\s<>"']+|^\\\\[^\s<>"']+|^(?:\.\.?|~)?\/[A-Za-z0-9_.-][^\s<>"']*|^[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+|^(?:\.[A-Za-z0-9_-]+|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z][A-Za-z0-9]{0,9})(?![A-Za-z0-9_/\\]|\.[A-Za-z0-9])/iu;
const ENTITY = /^&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);/u;
const TAG = /^<\/?[A-Za-z][^>\n]*>/u;
const AUTOLINK = /^<(?:https?:\/\/|ftp:\/\/|file:\/\/|mailto:)[^>\n]+>/iu;

function closingTicks(value: string, start: number, count: number): number | null {
  let cursor = start + count;
  while (cursor < value.length) {
    cursor = value.indexOf("`", cursor);
    if (cursor < 0) return null;
    let end = cursor;
    while (end < value.length && value[end] === "`") end += 1;
    if (end - cursor === count) return end;
    cursor = end;
  }
  return null;
}

function closingDestination(value: string, start: number): number | null {
  let depth = 0;
  let escaped = false;
  for (let cursor = start; cursor < value.length; cursor += 1) {
    const char = value[cursor];
    if (escaped) { escaped = false; continue; }
    if (char === "\\") escaped = true;
    else if (char === "(") depth += 1;
    else if (char === ")" && --depth === 0) return cursor + 1;
    else if (char === "\n") return null;
  }
  return null;
}

function inline(value: string): string {
  let result = "";
  let cursor = 0;
  while (cursor < value.length) {
    const char = value[cursor];
    if (char === "\\" && cursor + 1 < value.length && !/[A-Za-z0-9]/u.test(value[cursor + 1])) {
      result += value.slice(cursor, cursor + 2);
      cursor += 2;
      continue;
    }
    if (char === "`") {
      let count = 1;
      while (value[cursor + count] === "`") count += 1;
      const end = closingTicks(value, cursor, count);
      if (end !== null) { result += value.slice(cursor, end); cursor = end; continue; }
    }
    if (char === "]" && value[cursor + 1] === "(") {
      const end = closingDestination(value, cursor + 1);
      if (end !== null) { result += value.slice(cursor, end); cursor = end; continue; }
    }
    if (char === "<") {
      const protectedTag = AUTOLINK.exec(value.slice(cursor))?.[0] ?? TAG.exec(value.slice(cursor))?.[0];
      if (protectedTag) { result += protectedTag; cursor += protectedTag.length; continue; }
    }
    if (char === "&") {
      const entity = ENTITY.exec(value.slice(cursor))?.[0];
      if (entity) { result += entity; cursor += entity.length; continue; }
    }
    if (cursor === 0 || !/[A-Za-z0-9_]/u.test(value[cursor - 1])) {
      const protectedToken = PROTECTED.exec(value.slice(cursor))?.[0];
      if (protectedToken) { result += protectedToken; cursor += protectedToken.length; continue; }
    }
    result += char + (VOWEL.test(char) ? INSERTION : "");
    cursor += 1;
  }
  return result;
}

export function transformAlbuquerqueMarkdown(value: string): string {
  const lines = value.match(/[^\n]*\n|[^\n]+$/gu) ?? [];
  let result = "";
  let fenceChar: string | null = null;
  let fenceLength = 0;
  for (const line of lines) {
    const fence = FENCE.exec(line);
    if (fenceChar !== null) {
      result += line;
      if (fence && fence[1][0] === fenceChar && fence[1].length >= fenceLength && !line.slice(fence[0].length).trim()) {
        fenceChar = null;
        fenceLength = 0;
      }
      continue;
    }
    if (fence) {
      fenceChar = fence[1][0];
      fenceLength = fence[1].length;
      result += line;
      continue;
    }
    result += line.startsWith("    ") || line.startsWith("\t") || LINK_DEFINITION.test(line)
      ? line : inline(line);
  }
  return result;
}
