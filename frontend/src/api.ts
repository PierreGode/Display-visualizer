import type {
  ClaudeStatus,
  Display,
  Example,
  LoginResult,
  LoginStart,
  RunResult,
  UpdateStatus,
  UpdateTriggerResult,
} from "./types";

export async function fetchDisplays(): Promise<Display[]> {
  const r = await fetch("/api/displays");
  if (!r.ok) throw new Error(`GET /api/displays: ${r.status}`);
  return r.json();
}

export async function fetchExamples(): Promise<Example[]> {
  const r = await fetch("/api/examples");
  if (!r.ok) throw new Error(`GET /api/examples: ${r.status}`);
  return r.json();
}

export async function runCode(displayId: string, code: string): Promise<RunResult> {
  const r = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_id: displayId, code }),
  });
  if (!r.ok) throw new Error(`POST /api/run: ${r.status}`);
  return r.json();
}

export async function fetchUpdateStatus(force = false): Promise<UpdateStatus> {
  const r = await fetch(force ? "/api/update/check" : "/api/update/status", {
    method: force ? "POST" : "GET",
  });
  if (!r.ok) throw new Error(`update status: ${r.status}`);
  return r.json();
}

export async function triggerUpdate(): Promise<UpdateTriggerResult> {
  const r = await fetch("/api/update/pull", { method: "POST" });
  if (!r.ok) throw new Error(`update pull: ${r.status}`);
  return r.json();
}

export async function fetchClaudeStatus(): Promise<ClaudeStatus> {
  const r = await fetch("/api/claude/status");
  if (!r.ok) throw new Error(`GET /api/claude/status: ${r.status}`);
  return r.json();
}

export async function claudeLoginStart(): Promise<LoginStart> {
  const r = await fetch("/api/claude/login/start", { method: "POST" });
  if (!r.ok) throw new Error(`POST /api/claude/login/start: ${r.status}`);
  return r.json();
}

export async function claudeLoginSubmit(sessionId: string, code: string): Promise<LoginResult> {
  const r = await fetch("/api/claude/login/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, code }),
  });
  if (!r.ok) throw new Error(`POST /api/claude/login/submit: ${r.status}`);
  return r.json();
}

export async function claudeLoginCancel(sessionId: string): Promise<void> {
  await fetch("/api/claude/login/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {});
}

export async function claudeLogout(): Promise<void> {
  await fetch("/api/claude/logout", { method: "POST" }).catch(() => {});
}

export async function setClaudeProject(
  path: string,
): Promise<{ ok: boolean; project_dir?: string; error?: string }> {
  const r = await fetch("/api/claude/project", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`POST /api/claude/project: ${r.status}`);
  return r.json();
}

export interface StreamedEvent {
  type: string;
  [k: string]: unknown;
}

/** Open an SSE stream for a Claude chat turn. Yields decoded events until 'done'. */
export async function* streamClaudeChat(
  prompt: string,
  displayId: string | null,
  editorCode: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamedEvent> {
  const r = await fetch("/api/claude/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, display_id: displayId, editor_code: editorCode }),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`POST /api/claude/chat: ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const chunk = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          const ev = JSON.parse(payload) as StreamedEvent;
          if (ev.type === "done") return;
          yield ev;
        } catch {
          // Malformed line — skip.
        }
      }
    }
  }
}

