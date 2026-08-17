import type { Display } from "../types";

interface Props {
  display: Display;
  imageBase64: string | null;
  running: boolean;
}

export function Preview({ display, imageBase64, running }: Props) {
  const [cw, ch] = display.canvas;
  const [sx, sy, sw, sh] = display.screen_bbox;
  const bezelUrl = `/api/displays/${display.id}/bezel`;
  const isRound = display.shape === "round";

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-sm font-medium text-neutral-100">{display.name}</div>
          <div className="text-xs text-neutral-500">
            {display.resolution[0]}×{display.resolution[1]}px · mode {display.mode}
            {display.mode === "P" && display.palette ? ` · ${display.palette.length}-color palette` : ""}
          </div>
          {display.driver && (
            <div
              className="mt-0.5 text-[11px] text-neutral-600 font-mono"
              title="Preview is pixel-accurate to this driver. Use “Device code” for a ready-to-run program."
            >
              {display.family === "epaper"
                ? `waveshare_epd.${display.driver}`
                : `lib.${display.driver}`}
            </div>
          )}
        </div>
        <a
          href={display.waveshare_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-neutral-500 hover:text-neutral-300 underline underline-offset-2"
        >
          product page ↗
        </a>
      </div>

      <div className="preview-stage relative flex-1 grid-checker rounded-lg overflow-hidden border border-neutral-800 flex items-center justify-center p-6">
        <div
          className="preview-frame relative"
          style={{
            aspectRatio: `${cw} / ${ch}`,
            // Clamp by the stage's height (100cqh) as well as its width so this
            // box always has the bezel's exact aspect ratio — the screen
            // overlay below is placed as a percentage of it. Dropped as invalid
            // (falling back to .preview-frame) on browsers without cq units.
            width: `min(100%, 640px, calc(100cqh * ${cw} / ${ch}))`,
          }}
        >
          <img
            src={bezelUrl}
            alt={display.name}
            className="absolute inset-0 w-full h-full select-none pointer-events-none"
            draggable={false}
          />
          <div
            className="absolute overflow-hidden"
            style={{
              left: `${(sx / cw) * 100}%`,
              top: `${(sy / ch) * 100}%`,
              width: `${(sw / cw) * 100}%`,
              height: `${(sh / ch) * 100}%`,
              borderRadius: isRound ? "50%" : undefined,
            }}
          >
            {imageBase64 ? (
              <img
                src={`data:image/png;base64,${imageBase64}`}
                alt="render"
                className="w-full h-full"
                style={{
                  imageRendering: "pixelated",
                  // `contain`, not the default stretch: if a catalog entry's
                  // screen_bbox ever disagrees with the framebuffer's aspect
                  // ratio, show it letterboxed rather than distorting pixels
                  // the panel would render square.
                  objectFit: "contain",
                  transform: display.screen_rotation
                    ? `rotate(${display.screen_rotation}deg)`
                    : undefined,
                }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-xs text-neutral-500/70">
                {running ? "running…" : "run your code to render"}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
