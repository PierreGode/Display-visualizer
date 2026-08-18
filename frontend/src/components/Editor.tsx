import Monaco from "@monaco-editor/react";
import { useRef, useEffect, useMemo } from "react";
import type { Display, Example } from "../types";
import { exampleSupportsDisplay } from "../types";

interface Props {
  code: string;
  onChange: (v: string) => void;
  examples: Example[];
  onLoadExample: (ex: Example) => void;
  onLoadDeviceCode: () => void;
  onRun: () => void;
  running: boolean;
  display: Display;
}

export function Editor({ code, onChange, examples, onLoadExample, onLoadDeviceCode, onRun, running, display }: Props) {
  const onRunRef = useRef(onRun);
  useEffect(() => {
    onRunRef.current = onRun;
  }, [onRun]);

  const compatible = useMemo(
    () => examples.filter((ex) => exampleSupportsDisplay(ex, display)),
    [examples, display],
  );
  const hiddenCount = examples.length - compatible.length;

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-wrap items-center justify-between border-b border-neutral-800 bg-neutral-900 px-3 py-2 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs text-neutral-500 uppercase tracking-wider">Examples</span>
          <select
            onChange={(e) => {
              const ex = compatible.find((x) => x.id === e.target.value);
              if (ex) onLoadExample(ex);
              e.target.value = "";
            }}
            defaultValue=""
            className="bg-neutral-950 border border-neutral-800 rounded-md text-xs text-neutral-200 px-2 py-1 focus:outline-none focus:border-neutral-600"
            title={
              hiddenCount > 0
                ? `${hiddenCount} example${hiddenCount === 1 ? "" : "s"} hidden — not supported by this display`
                : undefined
            }
          >
            <option value="" disabled>
              Load example…
            </option>
            {compatible.map((ex) => (
              <option key={ex.id} value={ex.id}>
                {ex.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-auto">
        {display.device_snippet && (
          <button
            onClick={onLoadDeviceCode}
            title={`Load ready-to-run code using the real ${display.driver} driver — runs unchanged on the Pi`}
            className="rounded-md border border-neutral-700 hover:border-neutral-500 text-neutral-300 text-xs px-2.5 py-1.5 transition-colors whitespace-nowrap"
          >
            ⤓ Device code
          </button>
        )}
        <button
          onClick={onRun}
          disabled={running}
          className="rounded-md bg-emerald-500 hover:bg-emerald-400 disabled:bg-neutral-700 disabled:text-neutral-500 text-neutral-950 text-xs font-semibold px-3 py-1.5 transition-colors flex items-center gap-1.5"
        >
          {running ? (
            <>
              <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" opacity="0.25" />
                <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
              </svg>
              Running
            </>
          ) : (
            <>
              <span className="sm:hidden">▶ Run</span>
              <span className="hidden sm:inline">▶ Run (⌘/Ctrl+Enter)</span>
            </>
          )}
        </button>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <Monaco
          height="100%"
          defaultLanguage="python"
          theme="vs-dark"
          value={code}
          onChange={(v) => onChange(v ?? "")}
          options={{
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on",
            tabSize: 4,
            // Re-measure when the container resizes or is revealed (mobile tabs
            // hide the editor with display:none, so it must relayout on show).
            automaticLayout: true,
            fontFamily: '"JetBrains Mono", ui-monospace, monospace',
          }}
          onMount={(editor, monaco) => {
            editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onRunRef.current());
          }}
        />
      </div>
    </div>
  );
}
