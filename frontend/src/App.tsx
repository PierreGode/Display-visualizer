import { useEffect, useMemo, useState } from "react";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import type { ReactNode } from "react";
import { fetchDisplays, fetchExamples, runCode } from "./api";
import type { Display, Example, RunResult } from "./types";
import { exampleSupportsDisplay } from "./types";
import { AssistantPanel } from "./components/AssistantPanel";
import { DisplayPicker } from "./components/DisplayPicker";
import { Editor } from "./components/Editor";
import { Preview } from "./components/Preview";
import { OutputPanel } from "./components/OutputPanel";
import { UpdateBanner } from "./components/UpdateBanner";

const STORAGE_KEY = "waveshare-visualizer:state:v1";

interface PersistedState {
  displayId: string | null;
  code: string;
}

function loadPersisted(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedState) : null;
  } catch {
    return null;
  }
}

function savePersisted(s: PersistedState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // storage full or blocked; harmless
  }
}

/** Track whether we're on a phone-sized viewport (below Tailwind's md breakpoint). */
function useIsMobile(): boolean {
  const query = "(max-width: 767px)";
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setIsMobile(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}

type MobileTab = "display" | "code" | "preview" | "claude";

export default function App() {
  const [displays, setDisplays] = useState<Display[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [code, setCode] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const isMobile = useIsMobile();
  const [mobileTab, setMobileTab] = useState<MobileTab>("code");

  useEffect(() => {
    (async () => {
      try {
        const [ds, exs] = await Promise.all([fetchDisplays(), fetchExamples()]);
        setDisplays(ds);
        setExamples(exs);

        const persisted = loadPersisted();
        const initial = persisted?.displayId && ds.some((d) => d.id === persisted.displayId)
          ? persisted.displayId
          : ds[0]?.id ?? null;
        setSelectedId(initial);

        const initialDisplay = ds.find((d) => d.id === initial);
        if (persisted?.code) {
          setCode(persisted.code);
        } else if (exs.length && initialDisplay) {
          const firstCompatible = exs.find((ex) => exampleSupportsDisplay(ex, initialDisplay));
          setCode((firstCompatible ?? exs[0]).code);
        }
      } catch (e) {
        setLoadError(String(e));
      }
    })();
  }, []);

  useEffect(() => {
    if (selectedId) savePersisted({ displayId: selectedId, code });
  }, [selectedId, code]);

  const selected = useMemo(
    () => displays.find((d) => d.id === selectedId) ?? null,
    [displays, selectedId],
  );

  const layout = useDefaultLayout({
    // v2: previous version stored a broken layout because Panel size props
    // were passed as numbers (interpreted as pixels, not percentages).
    id: assistantOpen ? "main-with-ai-v2" : "main-v2",
    storage: typeof window !== "undefined" ? window.localStorage : undefined,
    panelIds: assistantOpen
      ? ["sidebar", "workspace", "preview", "assistant"]
      : ["sidebar", "workspace", "preview"],
  });

  function toggleAssistant() {
    if (isMobile) {
      setAssistantOpen(true);
      setMobileTab("claude");
    } else {
      setAssistantOpen((v) => !v);
    }
  }

  async function handleRun() {
    if (!selected || running) return;
    setRunning(true);
    // On phones the preview lives on its own tab — jump to it so the user sees
    // the result without hunting for the tab.
    if (isMobile) setMobileTab("preview");
    try {
      const r = await runCode(selected.id, code);
      setResult(r);
    } catch (e) {
      setResult({
        ok: false,
        stdout: "",
        stderr: `Request failed: ${String(e)}`,
        friendly: "Couldn't reach the server. Check that the visualizer service is running, then try again.",
        image_base64: null,
        duration_ms: 0,
      });
    } finally {
      setRunning(false);
    }
  }

  if (loadError) {
    return (
      <div className="h-screen flex items-center justify-center text-red-400 font-mono text-sm p-6">
        Failed to load: {loadError}
      </div>
    );
  }

  if (!selected) {
    return (
      <div className="h-screen flex items-center justify-center text-neutral-500 text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col" style={{ height: "100dvh" }}>
      <header className="border-b border-neutral-800 bg-neutral-900 px-3 sm:px-4 py-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 shrink-0 rounded bg-emerald-500 flex items-center justify-center text-neutral-900 font-bold text-xs">
            D
          </div>
          <h1 className="font-semibold text-neutral-100 text-sm sm:text-base truncate">
            <span className="sm:hidden">Display Sim</span>
            <span className="hidden sm:inline">Display Visualizer</span>
          </h1>
          <span className="text-xs text-neutral-500 hidden md:inline">
            · pure Python simulator
          </span>
        </div>
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <UpdateBanner />
          <span className="text-xs text-neutral-500 hidden sm:inline">{displays.length} displays</span>
          <button
            onClick={toggleAssistant}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
              (isMobile ? mobileTab === "claude" : assistantOpen)
                ? "bg-emerald-500 border-emerald-500 text-neutral-950"
                : "bg-neutral-900 border-neutral-800 text-neutral-200 hover:border-neutral-700"
            }`}
            title="AI assistant (Claude)"
          >
            <span className="sm:hidden">✨</span>
            <span className="hidden sm:inline">✨ Ask Claude</span>
          </button>
        </div>
      </header>

      {isMobile ? (
        <>
          <div className="flex-1 min-h-0 relative">
            <MobilePane active={mobileTab === "display"}>
              <aside className="h-full p-3 overflow-y-auto">
                <DisplayPicker
                  displays={displays}
                  selectedId={selectedId}
                  onSelect={(id) => {
                    setSelectedId(id);
                    setMobileTab("code");
                  }}
                />
              </aside>
            </MobilePane>

            <MobilePane active={mobileTab === "code"}>
              <div className="h-full flex flex-col">
                <div className="flex-1 min-h-0">
                  <Editor
                    code={code}
                    onChange={setCode}
                    examples={examples}
                    onLoadExample={(ex) => setCode(ex.code)}
                    onLoadDeviceCode={() => selected.device_snippet && setCode(selected.device_snippet)}
                    onRun={handleRun}
                    running={running}
                    display={selected}
                  />
                </div>
                <OutputPanel result={result} running={running} />
              </div>
            </MobilePane>

            <MobilePane active={mobileTab === "preview"}>
              <div className="h-full p-4 overflow-hidden bg-neutral-950">
                <Preview display={selected} imageBase64={result?.image_base64 ?? null} running={running} />
              </div>
            </MobilePane>

            <MobilePane active={mobileTab === "claude"}>
              {assistantOpen ? (
                <AssistantPanel
                  displayId={selected.id}
                  editorCode={code}
                  onInsertCode={(c) => {
                    setCode(c);
                    setMobileTab("code");
                  }}
                  onClose={() => setMobileTab("code")}
                />
              ) : (
                <div className="h-full flex items-center justify-center p-6 text-sm text-neutral-500">
                  Loading assistant…
                </div>
              )}
            </MobilePane>
          </div>

          <nav className="border-t border-neutral-800 bg-neutral-900 grid grid-cols-4 shrink-0">
            <MobileTabButton label="Displays" icon="▦" active={mobileTab === "display"} onClick={() => setMobileTab("display")} />
            <MobileTabButton label="Code" icon="‹›" active={mobileTab === "code"} onClick={() => setMobileTab("code")} />
            <MobileTabButton label="Preview" icon="▷" active={mobileTab === "preview"} onClick={() => setMobileTab("preview")} />
            <MobileTabButton
              label="Claude"
              icon="✨"
              active={mobileTab === "claude"}
              onClick={() => {
                setAssistantOpen(true);
                setMobileTab("claude");
              }}
            />
          </nav>
        </>
      ) : (
        <div className="flex-1 min-h-0">
          <Group
            orientation="horizontal"
            defaultLayout={layout.defaultLayout}
            onLayoutChanged={layout.onLayoutChanged}
            className="h-full"
          >
            <Panel id="sidebar" defaultSize="18%" minSize="12%" maxSize="35%" className="bg-neutral-950">
              <aside className="h-full p-3 overflow-hidden">
                <DisplayPicker
                  displays={displays}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </aside>
            </Panel>

            <VerticalSeparator />

            <Panel id="workspace" defaultSize="42%" minSize="20%" className="flex flex-col min-w-0">
              <div className="flex-1 min-h-0">
                <Editor
                  code={code}
                  onChange={setCode}
                  examples={examples}
                  onLoadExample={(ex) => setCode(ex.code)}
                  onLoadDeviceCode={() => selected.device_snippet && setCode(selected.device_snippet)}
                  onRun={handleRun}
                  running={running}
                  display={selected}
                />
              </div>
              <OutputPanel result={result} running={running} />
            </Panel>

            <VerticalSeparator />

            <Panel id="preview" defaultSize={assistantOpen ? "22%" : "40%"} minSize="20%" className="bg-neutral-950">
              <div className="h-full p-4 overflow-hidden">
                <Preview display={selected} imageBase64={result?.image_base64 ?? null} running={running} />
              </div>
            </Panel>

            {assistantOpen && (
              <>
                <VerticalSeparator />
                <Panel id="assistant" defaultSize="20%" minSize="15%" maxSize="45%">
                  <AssistantPanel
                    displayId={selected.id}
                    editorCode={code}
                    onInsertCode={setCode}
                    onClose={() => setAssistantOpen(false)}
                  />
                </Panel>
              </>
            )}
          </Group>
        </div>
      )}
    </div>
  );
}

/** A mobile tab body: stays mounted (so Monaco/preview state survives tab
 *  switches) but is hidden with display:none when inactive. */
function MobilePane({ active, children }: { active: boolean; children: ReactNode }) {
  return <div className={active ? "absolute inset-0" : "hidden"}>{children}</div>;
}

function MobileTabButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
        active ? "text-emerald-400" : "text-neutral-500 hover:text-neutral-300"
      }`}
    >
      <span className="text-base leading-none">{icon}</span>
      {label}
    </button>
  );
}

/** Thin vertical drag handle between panels — hover-highlighted so users know to grab it. */
function VerticalSeparator() {
  return (
    <Separator className="relative w-px bg-neutral-800 hover:bg-emerald-500/70 transition-colors cursor-col-resize">
      {/* Wider invisible hit target so the handle is easy to grab without overlapping panel content. */}
      <span className="absolute inset-y-0 -left-1 -right-1 z-10" aria-hidden />
    </Separator>
  );
}
