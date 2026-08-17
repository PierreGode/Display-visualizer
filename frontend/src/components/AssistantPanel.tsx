import { useCallback, useEffect, useRef, useState } from "react";
import {
  claudeLoginStart,
  claudeLoginSubmit,
  claudeLogout,
  fetchClaudeStatus,
  setClaudeProject,
  streamClaudeChat,
} from "../api";
import type { AssistantBlock, ChatMessage, ClaudeStatus } from "../types";

interface Props {
  displayId: string | null;
  editorCode: string;
  onInsertCode: (code: string) => void;
  onClose: () => void;
}

function extractCodeBlocks(text: string): string[] {
  const out: string[] = [];
  const re = /```(?:python|py)?\n([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) out.push(m[1].trim());
  return out;
}

export function AssistantPanel({ displayId, editorCode, onInsertCode, onClose }: Props) {
  const [status, setStatus] = useState<ClaudeStatus | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await fetchClaudeStatus());
    } catch (e) {
      setStatus({
        cli_installed: false,
        cli_version: null,
        authenticated: false,
        project_dir: "?",
        project_dir_exists: false,
        error: String(e),
      });
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, busy]);

  async function send() {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setError(null);

    const userMsg: ChatMessage = { role: "user", blocks: [{ type: "text", text: prompt }] };
    const assistantMsg: ChatMessage = { role: "assistant", blocks: [] };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setBusy(true);

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      for await (const ev of streamClaudeChat(prompt, displayId, editorCode, ac.signal)) {
        if (ev.type === "assistant") {
          const newBlocks = ev.blocks as AssistantBlock[];
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              role: "assistant",
              blocks: [...copy[copy.length - 1].blocks, ...newBlocks],
            };
            return copy;
          });
        } else if (ev.type === "error") {
          setError(String(ev.message));
          if (ev.auth) refreshStatus();
        } else if (ev.type === "result") {
          // Turn finished. Surface an error result (e.g. a revoked session or
          // a hit step-limit) that didn't already arrive as an error event.
          if (ev.is_error && ev.message) setError(String(ev.message));
          if (ev.auth) refreshStatus();
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(String(e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
  }

  const isReady = status?.cli_installed && (status?.authenticated ?? true);

  return (
    <aside className="w-full h-full border-l border-neutral-800 bg-neutral-950 flex flex-col min-h-0">
      <div className="flex items-center justify-between border-b border-neutral-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold text-neutral-100">Claude</span>
          <span className="text-[10px] text-neutral-500">agent</span>
        </div>
        <button
          onClick={onClose}
          className="text-neutral-500 hover:text-neutral-200 text-sm"
          title="Close"
        >
          ×
        </button>
      </div>

      <div className="border-b border-neutral-800 px-3 py-2 text-[11px] text-neutral-400 space-y-0.5">
        {!status ? (
          <div>Checking Claude status…</div>
        ) : !status.cli_installed ? (
          <div className="text-amber-300">
            <div>Claude CLI not installed.</div>
            <div className="text-neutral-500">
              On the Pi: <code className="text-neutral-300">npm install -g @anthropic-ai/claude-code</code>
            </div>
          </div>
        ) : !status.authenticated ? (
          <LoginBox onLoggedIn={refreshStatus} version={status.cli_version} />
        ) : (
          <div className="space-y-1">
            <div className="text-emerald-300 flex items-center justify-between gap-2">
              <div>
                Ready · {status.cli_version}
                {status.email ? (
                  <>
                    {" · "}
                    <span className="text-neutral-300">{status.email}</span>
                  </>
                ) : null}
              </div>
              <button
                className="text-neutral-500 hover:text-neutral-300 underline shrink-0"
                onClick={async () => {
                  await claudeLogout();
                  refreshStatus();
                }}
              >
                log out
              </button>
            </div>
            <ProjectDirEditor
              projectDir={status.project_dir}
              exists={status.project_dir_exists}
              onChanged={refreshStatus}
            />
          </div>
        )}
      </div>

      <div ref={scrollerRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-xs text-neutral-500 space-y-2">
            <div>Ask Claude to write display code for you. Examples:</div>
            <ul className="space-y-1 list-disc list-inside">
              <li>Draw a battery gauge on the currently selected display</li>
              <li>I have a project in /project — read main.py and adapt it to run on this 4.2" e-paper</li>
              <li>Show the current time in large digits</li>
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageView
            key={i}
            msg={m}
            onInsertCode={onInsertCode}
          />
        ))}
        {busy && (
          <div className="text-xs text-neutral-500 flex items-center gap-2">
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" opacity="0.25" />
              <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
            </svg>
            Thinking…
          </div>
        )}
        {error && (
          <div className="text-xs text-red-400 font-mono whitespace-pre-wrap break-words">
            {error}
          </div>
        )}
      </div>

      <div className="border-t border-neutral-800 p-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={isReady ? "Ask Claude… (Ctrl/⌘+Enter to send)" : "Login required — see status above"}
          disabled={!isReady || busy}
          rows={3}
          className="w-full resize-none rounded-md bg-neutral-900 border border-neutral-800 text-neutral-100 text-sm p-2 focus:outline-none focus:border-neutral-600 disabled:opacity-50 font-mono"
        />
        <div className="flex justify-between items-center mt-1">
          <span className="text-[10px] text-neutral-500">
            {displayId ? `context: ${displayId}` : "no display selected"}
          </span>
          {busy ? (
            <button
              onClick={cancel}
              className="rounded-md bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs px-3 py-1"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={send}
              disabled={!isReady || !input.trim()}
              className="rounded-md bg-emerald-500 hover:bg-emerald-400 disabled:bg-neutral-700 disabled:text-neutral-500 text-neutral-950 text-xs font-semibold px-3 py-1"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

function ProjectDirEditor({
  projectDir,
  exists,
  onChanged,
}: {
  projectDir: string;
  exists: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(projectDir);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setValue(projectDir);
  }, [projectDir]);

  async function save() {
    if (!value.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await setClaudeProject(value.trim());
      if (res.ok) {
        setEditing(false);
        onChanged();
      } else {
        setErr(res.error || "could not set project directory");
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-1.5 flex-wrap text-neutral-500">
        <span>project:</span>
        <span className={exists ? "text-neutral-300" : "text-amber-300"}>{projectDir}</span>
        {!exists && <span className="text-amber-300">(missing)</span>}
        <button className="underline hover:text-neutral-300" onClick={() => setEditing(true)}>
          change
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex gap-1.5">
        <input
          value={value}
          autoFocus
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") {
              setEditing(false);
              setErr(null);
            }
          }}
          placeholder="/home/you/my-project"
          disabled={busy}
          className="flex-1 min-w-0 rounded-md bg-neutral-900 border border-neutral-800 text-neutral-100 text-[11px] px-2 py-1 focus:outline-none focus:border-neutral-600 font-mono disabled:opacity-50"
        />
        <button
          onClick={save}
          disabled={busy || !value.trim()}
          className="rounded-md bg-emerald-500 hover:bg-emerald-400 disabled:bg-neutral-700 disabled:text-neutral-500 text-neutral-950 text-[11px] font-semibold px-2 py-1"
        >
          {busy ? "…" : "Set"}
        </button>
        <button
          onClick={() => {
            setEditing(false);
            setErr(null);
          }}
          className="text-neutral-500 hover:text-neutral-300 text-[11px] px-1"
        >
          cancel
        </button>
      </div>
      <div className="text-neutral-600">Any directory the Pi service can read — this session's project for Claude.</div>
      {err && <div className="text-red-400 break-words">{err}</div>}
    </div>
  );
}

function LoginBox({ onLoggedIn, version }: { onLoggedIn: () => void; version: string | null }) {
  const [phase, setPhase] = useState<"idle" | "starting" | "awaiting_code" | "submitting">("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function begin() {
    setErr(null);
    setPhase("starting");
    try {
      const res = await claudeLoginStart();
      if (res.error || !res.url || !res.session_id) {
        setErr(res.error || "could not start login");
        setPhase("idle");
        return;
      }
      setUrl(res.url);
      setSessionId(res.session_id);
      setPhase("awaiting_code");
      window.open(res.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setErr(String(e));
      setPhase("idle");
    }
  }

  async function finish() {
    if (!sessionId || !code.trim()) return;
    setErr(null);
    setPhase("submitting");
    try {
      const res = await claudeLoginSubmit(sessionId, code.trim());
      if (res.ok) {
        onLoggedIn();
        return;
      }
      setErr(res.error || "login failed");
      if (res.retryable) {
        // Session is still parked at the prompt — let them paste again.
        setCode("");
        setPhase("awaiting_code");
      } else {
        // Session was torn down — go back to the start.
        setSessionId(null);
        setUrl(null);
        setCode("");
        setPhase("idle");
      }
    } catch (e) {
      setErr(String(e));
      setPhase("awaiting_code");
    }
  }

  return (
    <div className="text-amber-300 space-y-1.5">
      <div>Claude CLI installed ({version}) — not signed in.</div>

      {phase === "idle" && (
        <button
          onClick={begin}
          className="rounded-md bg-emerald-500 hover:bg-emerald-400 text-neutral-950 text-xs font-semibold px-3 py-1"
        >
          Sign in to Claude
        </button>
      )}

      {phase === "starting" && <div className="text-neutral-400">Starting sign-in…</div>}

      {(phase === "awaiting_code" || phase === "submitting") && (
        <div className="space-y-1.5">
          <div className="text-neutral-400">
            A Claude authorization page opened in a new tab. If it didn't,{" "}
            <a href={url ?? "#"} target="_blank" rel="noreferrer" className="underline text-neutral-200">
              open it here
            </a>
            . Approve access, then paste the code you're given below.
          </div>
          <div className="flex gap-1.5">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") finish();
              }}
              placeholder="Paste authorization code"
              disabled={phase === "submitting"}
              className="flex-1 rounded-md bg-neutral-900 border border-neutral-800 text-neutral-100 text-xs px-2 py-1 focus:outline-none focus:border-neutral-600 disabled:opacity-50 font-mono"
            />
            <button
              onClick={finish}
              disabled={phase === "submitting" || !code.trim()}
              className="rounded-md bg-emerald-500 hover:bg-emerald-400 disabled:bg-neutral-700 disabled:text-neutral-500 text-neutral-950 text-xs font-semibold px-3 py-1"
            >
              {phase === "submitting" ? "…" : "Finish"}
            </button>
          </div>
        </div>
      )}

      {err && <div className="text-red-400 font-mono break-words">{err}</div>}
    </div>
  );
}

function MessageView({ msg, onInsertCode }: { msg: ChatMessage; onInsertCode: (code: string) => void }) {
  const isUser = msg.role === "user";
  return (
    <div className={`text-xs ${isUser ? "text-neutral-200" : "text-neutral-100"}`}>
      <div className={`text-[10px] uppercase tracking-wider mb-1 ${isUser ? "text-neutral-500" : "text-emerald-400"}`}>
        {isUser ? "You" : "Claude"}
      </div>
      {msg.blocks.map((b, i) => {
        if (b.type === "text" && b.text) {
          const codeBlocks = extractCodeBlocks(b.text);
          return (
            <div key={i} className="whitespace-pre-wrap break-words leading-relaxed">
              {b.text}
              {codeBlocks.map((code, j) => (
                <div key={j} className="mt-2">
                  <button
                    onClick={() => onInsertCode(code)}
                    className="text-[10px] rounded-md bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20 px-2 py-0.5"
                  >
                    Insert code block {codeBlocks.length > 1 ? `#${j + 1}` : ""} into editor →
                  </button>
                </div>
              ))}
            </div>
          );
        }
        if (b.type === "tool_use") {
          return (
            <div key={i} className="mt-1 text-[10px] font-mono text-neutral-500">
              → tool: <span className="text-neutral-400">{b.name}</span>
              {b.input && Object.keys(b.input).length > 0 && (
                <span className="text-neutral-600"> ({Object.keys(b.input).join(", ")})</span>
              )}
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}
