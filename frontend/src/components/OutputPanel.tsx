import type { RunResult } from "../types";

interface Props {
  result: RunResult | null;
  running: boolean;
}

export function OutputPanel({ result, running }: Props) {
  const hasStdout = result?.stdout?.trim();
  const hasStderr = result?.stderr?.trim();
  const friendly = result?.friendly?.trim();
  // Only show the raw traceback separately when it adds detail beyond the
  // friendly summary (avoids showing the same text twice).
  const showRawDetails = !!hasStderr && result?.stderr?.trim() !== friendly;
  const status = running
    ? "Running…"
    : result
      ? result.ok
        ? `Rendered in ${result.duration_ms}ms`
        : `Failed in ${result.duration_ms}ms`
      : "Idle";

  return (
    <div className="flex flex-col gap-1 border-t border-neutral-800 bg-neutral-950 p-3 font-mono text-xs">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            running
              ? "bg-yellow-400 animate-pulse"
              : result?.ok
                ? "bg-emerald-400"
                : result
                  ? "bg-red-400"
                  : "bg-neutral-600"
          }`}
        />
        <span className="text-neutral-400">{status}</span>
      </div>
      {hasStdout && (
        <pre className="whitespace-pre-wrap text-neutral-300 max-h-24 overflow-y-auto">
{result!.stdout}
        </pre>
      )}
      {friendly && (
        <div className="flex gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-2 text-red-200">
          <span aria-hidden className="select-none leading-5">⚠</span>
          <p className="whitespace-pre-wrap font-sans leading-5">{friendly}</p>
        </div>
      )}
      {showRawDetails && (
        <details className="text-neutral-500">
          <summary className="cursor-pointer select-none hover:text-neutral-300">
            {friendly ? "Show full traceback" : "Details"}
          </summary>
          <pre className="mt-1 whitespace-pre-wrap text-red-400/80 max-h-40 overflow-y-auto">
{result!.stderr}
          </pre>
        </details>
      )}
    </div>
  );
}
