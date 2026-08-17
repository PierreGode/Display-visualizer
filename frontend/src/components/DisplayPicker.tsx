import type { Display, DisplayFamily } from "../types";
import { useMemo, useState } from "react";

interface Props {
  displays: Display[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const FAMILY_LABELS: Record<DisplayFamily, string> = {
  epaper: "E-Paper",
  lcd: "LCD",
  oled: "OLED",
  char: "Char",
};

export function DisplayPicker({ displays, selectedId, onSelect }: Props) {
  const [family, setFamily] = useState<DisplayFamily | "all">("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    return displays.filter((d) => {
      if (family !== "all" && d.family !== family) return false;
      if (query && !d.name.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [displays, family, query]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search displays…"
          className="w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-neutral-600 focus:outline-none"
        />
        <div className="flex gap-1">
          {(["all", "epaper", "lcd", "oled", "char"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFamily(f)}
              className={`flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                family === f
                  ? "bg-neutral-100 text-neutral-900"
                  : "bg-neutral-900 text-neutral-400 border border-neutral-800 hover:text-neutral-200"
              }`}
            >
              {f === "all" ? "All" : FAMILY_LABELS[f]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1 overflow-y-auto pr-1" style={{ maxHeight: "calc(100vh - 200px)" }}>
        {filtered.map((d) => {
          const active = d.id === selectedId;
          return (
            <button
              key={d.id}
              onClick={() => onSelect(d.id)}
              className={`text-left rounded-md border px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-neutral-100 text-neutral-900 border-neutral-100"
                  : "bg-neutral-900/50 border-neutral-800 text-neutral-200 hover:border-neutral-700 hover:bg-neutral-900"
              }`}
            >
              <div className="font-medium truncate">{d.name}</div>
              <div className={`text-xs mt-0.5 ${active ? "text-neutral-600" : "text-neutral-500"}`}>
                {d.resolution[0]}×{d.resolution[1]} · {FAMILY_LABELS[d.family]}
                {d.shape === "round" ? " · round" : ""}
                {d.mode === "P" && d.palette ? ` · ${d.palette.length}-color` : ""}
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="text-sm text-neutral-500 px-3 py-4">No displays match.</div>
        )}
      </div>
    </div>
  );
}
