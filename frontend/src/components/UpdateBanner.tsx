import { useCallback, useEffect, useRef, useState } from "react";
import { fetchUpdateStatus, triggerUpdate } from "../api";
import type { UpdateStatus } from "../types";

const POLL_INTERVAL_MS = 15 * 60 * 1000; // 15 min

type Phase = "idle" | "checking" | "updating" | "restarting" | "up-to-date";

export function UpdateBanner() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const refresh = useCallback(async (force = false) => {
    try {
      const s = await fetchUpdateStatus(force);
      setStatus(s);
    } catch {
      // network hiccup — try again next tick
    }
  }, []);

  useEffect(() => {
    refresh();
    timerRef.current = window.setInterval(() => refresh(false), POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [refresh]);

  const handleUpdate = useCallback(async () => {
    if (!status?.update_available || !status.can_apply) return;
    setPhase("updating");
    setMessage(null);
    try {
      const res = await triggerUpdate();
      if (!res.ok) {
        setPhase("idle");
        setMessage(res.error || "update failed to start");
        return;
      }
      setMessage(res.message ?? null);
      setPhase("restarting");
      // Poll until the backend comes back with a matching remote sha or times out.
      const targetSha = status.remote_sha;
      const started = Date.now();
      const deadline = started + 5 * 60 * 1000; // 5 min hard cap
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 4000));
        try {
          const s = await fetchUpdateStatus(false);
          if (s.local_sha && s.local_sha === targetSha) {
            setStatus(s);
            setPhase("up-to-date");
            setMessage("Updated. Reloading…");
            setTimeout(() => window.location.reload(), 1200);
            return;
          }
          setStatus(s);
        } catch {
          // Backend down mid-restart — that's expected. Keep polling.
        }
      }
      setPhase("idle");
      setMessage("Update didn't complete in 5 minutes. Check the update log on the Pi.");
    } catch (e) {
      setPhase("idle");
      setMessage(String(e));
    }
  }, [status]);

  if (!status || !status.in_git_repo) return null;
  if (!status.update_available && phase === "idle") return null;

  const busy = phase === "updating" || phase === "restarting";

  return (
    <div
      className={`flex items-center gap-2 rounded-md px-2.5 py-1 text-xs border ${
        phase === "up-to-date"
          ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
          : "bg-amber-500/10 border-amber-500/40 text-amber-200"
      }`}
      title={
        status.latest_commit_message
          ? `Latest: ${status.latest_commit_message}`
          : undefined
      }
    >
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-current" />
      {phase === "updating" && <span>Starting update…</span>}
      {phase === "restarting" && (
        <span>
          Pulling {status.local_short} → {status.remote_short}, restarting…
        </span>
      )}
      {phase === "up-to-date" && <span>{message ?? "Up to date"}</span>}
      {phase === "idle" && status.update_available && (
        <>
          <span>
            Update available:{" "}
            <span className="font-mono">
              {status.local_short}→{status.remote_short}
            </span>
            {status.behind > 1 && ` · ${status.behind} commits`}
          </span>
          {status.can_apply ? (
            <button
              onClick={handleUpdate}
              disabled={busy}
              className="rounded bg-amber-400 hover:bg-amber-300 text-neutral-950 font-semibold px-2 py-0.5"
            >
              Update
            </button>
          ) : (
            <span className="text-neutral-500">(no update.sh — pull manually)</span>
          )}
        </>
      )}
      {message && phase === "idle" && (
        <span className="ml-2 text-red-400 max-w-[280px] truncate" title={message}>
          {message}
        </span>
      )}
    </div>
  );
}
