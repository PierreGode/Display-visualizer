# Display Visualizer

Web-based simulator for [Waveshare](https://www.waveshare.com/product/displays.htm) e-paper, LCD and OLED displays. Write Python in the browser, hit run, and see your framebuffer rendered inside a picture of the display — no hardware required.

Designed to run on a Raspberry Pi 4/5 on your LAN, but the backend is pure Python and works on any Linux/macOS/Windows machine with Python 3.10+.

## Features

- **55+ Waveshare displays** out of the box across e-paper (mono, grayscale, red/black/white, 4-color G, 6/7-color F/E), LCD (ST7789/ILI9341/ILI9486/ST7735S), round LCD (GC9A01/ST7701S/ST77916), and OLED (SSD1306/SH1106/SSD1327/SSD1351/SSD1309).
- **Round displays render round** — circular LCDs mask the framebuffer to the inscribed circle so corners go black, exactly like the real glass, with a matching circular bezel.
- **Pixel-accurate to the panel** — the preview runs the *exact* quantization each controller performs: mono dithers like `getbuffer`, 4-gray e-paper shows only its 4 levels, 7/6/4-color e-paper uses the panel's real inks (byte-identical to the vendor `getbuffer`, verified), and LCD/RGB-OLED are reduced to RGB565. What you see is what the glass shows.
- **Two ways to write code, same pixels:**
  - **Quick sketches** — the unified `from waveshare_sim import display; display.show(img)` API.
  - **Device-ready** — click **⤓ Device code** to load a program that uses the *real* Waveshare driver for the selected panel (`from waveshare_epd import epd7in3f; epd.display(epd.getbuffer(img))`, or `from lib import LCD_1inch28` / `OLED_1in3`). It runs **unchanged on the Pi**. Both paths share one fidelity core (`backend/sim/quantize.py`), so the preview is identical either way.
- **Claude Code assistant built in** — click "Ask Claude" to have an in-browser agent that knows every display's capabilities, can read files from a configured project dir, and can run its own code against the simulator to iterate.
- **PIL/Pillow-native** — your code uses the same `Image`, `ImageDraw`, `ImageFont` calls that real Waveshare examples use.
- **Sandboxed** — user code runs in a subprocess with a wall-clock timeout, isolated from the backend source.
- **Bring your own photos** — the shipped bezels are synthesised SVGs, but drop a real product photo into `backend/assets/photos/` and it takes over automatically.

## Quickstart on a Raspberry Pi

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/PierreGode/waveshare-displays_visualizer/main/install.sh)"
```

Then open `http://<pi-ip>:8080` from any device on your LAN.

The installer:
- installs apt deps and Node.js 20
- clones the repo to `/opt/waveshare-visualizer`
- builds the frontend
- installs a systemd unit (`waveshare-visualizer.service`)
- starts it on port 8080

Change the port with `PORT=9000 sudo -E bash install.sh`, or the install location with `INSTALL_DIR=/srv/wsv sudo -E bash install.sh`.

## Local development

```bash
# Backend (from repo root)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn backend.main:app --reload --port 8080

# Frontend (in another terminal)
cd frontend
npm install
npm run dev   # serves at http://localhost:5173 with /api proxied to :8080
```

For a production build served by the backend, `npm run build` writes to `frontend/dist/` and FastAPI mounts it at `/`.

## Writing display code

Every snippet starts with:

```python
from waveshare_sim import display
from PIL import Image, ImageDraw
```

`display` is preconfigured for the selected display:

| attribute | description |
|---|---|
| `display.width`, `display.height` | framebuffer dimensions in pixels |
| `display.mode` | PIL image mode — `"1"`, `"L"`, `"RGB"`, or `"P"` |
| `display.shape` | `"rect"` or `"round"` — round masks the framebuffer to the inscribed circle |
| `display.palette` | list of hex colors for `"P"` / OLED / mono, else `None` |
| `display.bg`, `display.fg` | convenient background / foreground values matching `mode` |
| `display.show(img)` | render `img` as the current framebuffer |
| `display.clear()` | show a blank framebuffer |
| `display.blank()` | return a fresh `Image` sized to the display |

Typical code:

```python
img = Image.new(display.mode, (display.width, display.height), display.bg)
draw = ImageDraw.Draw(img)
draw.text((4, 4), "Hello", fill=display.fg)
display.show(img)
```

Anything you pass to `display.show()` is automatically resized (if needed) and quantized to the display's palette — so what you see in the browser matches what a real device would render, including e-paper dithering.

## AI assistant (Claude Code)

The visualizer embeds a Claude Code agent so you can ask it to write display code, adapt existing code from a project directory, and iterate by running the code against the simulator.

**Sign in — entirely from the browser.** The installer installs the `claude` CLI globally and points the service at a writable config dir, so you don't need to SSH in to authenticate:

1. Open the app and click **✨ Ask Claude** in the header.
2. If not signed in, click **Sign in to Claude**. A Claude authorization page opens in a new tab.
3. Approve access, copy the code it gives you, paste it back into the panel, and click **Finish**.

That's it — the agent is ready. Click **log out** in the panel to sign out. (If you'd already run `claude login` on the Pi before installing, that session is carried over automatically and you're signed in from the start.)

**Optional — give Claude a project to read:**

```bash
sudo mkdir -p /project && sudo cp -r ~/my-epaper-code/* /project/
sudo chown -R pi:pi /project
```

Example prompts:

> Draw a battery gauge on the currently selected display.

> I have this project in /project — read src/main.py and adapt it to run on this 4.2inch v2.

> Show the current time and today's temperature in big digits.

**What Claude can and can't do:**

- ✅ List displays, get details, and see the display currently selected in the UI
- ✅ Run its own code against the simulator (`render_on_display`) and see if it worked
- ✅ Read and list files inside `CLAUDE_PROJECT_DIR` (default `/project`)
- ✅ Insert code into your editor with one click
- ❌ Read anything outside the project dir — the tools reject paths that resolve outside it
- ❌ Write files, edit files, or shell out — those built-in tools are disabled

Change the sandbox root with `CLAUDE_PROJECT_DIR=/path/to/your/code` in the systemd unit (or in your environment when running locally).

If you don't want the AI assistant, install with `SKIP_CLAUDE=1 sudo -E bash install.sh` — everything else keeps working.

## Adding real product photos

The default bezels are procedural SVGs. To use a real Waveshare product photo:

1. Save it as `backend/assets/photos/{display_id}.jpg` (or `.png`, `.webp`). The ID must match `displays.json` exactly, e.g. `epd7in5_v2.jpg`.
2. Update the `screen_bbox` for that display in `backend/displays.json` — this is `[x, y, w, h]` in pixel coordinates of your photo, marking where the screen sits.
3. Reload. The backend serves the photo instead of the generated bezel.

## Adding new displays

Add an entry to `backend/displays.json` — no code changes required. Fields:

```json
{
  "id": "epd1in64g",
  "name": "1.64inch e-Paper (G)",
  "family": "epaper",         // "epaper" | "lcd" | "oled"
  "resolution": [168, 168],   // framebuffer WxH in pixels
  "mode": "P",                // PIL mode: "1", "L", "RGB", "P"
  "palette": ["#ffffff", "#000000", "#c62828", "#f9a825"],
  "shape": "rect",            // "rect" (default) or "round" for circular LCDs
  "bezel": "epd1in64g.svg",   // filename hint; generated procedurally if no photo present
  "screen_bbox": [60, 60, 400, 400],
  "screen_rotation": 0,
  "waveshare_url": "https://www.waveshare.com/1.64inch-e-paper-module-g.htm"
}
```

For a **round** display, set `"shape": "round"` and make `screen_bbox` the bounding square of the circle (equal width and height). The visualizer inscribes the circle in that square: it blanks the framebuffer corners to background in the sim, clips the preview to a circle, and synthesises a circular PCB bezel. `display.shape` is also exposed to user code so snippets can adapt their layout. Examples in the catalog: `lcd1in28_round` (GC9A01, 240×240), `lcd1in85_round` (ST77916, 360×360), `lcd2in1_round` (ST7701S, 480×480).

## Security notes

User Python code is executed in a subprocess with `PYTHONPATH` scoped to the sim runtime, a 5-second wall-clock timeout, and a per-run tempdir. **Network is not blocked at the OS level** and Python's stdlib is fully available. This is fine for a LAN tool but do not expose the port to the public internet without additional isolation (nsjail, gVisor, or a container per run).

## Roadmap

- Compatibility shim for `waveshare_epd.epd*` and common LCD driver module names, so upstream Waveshare examples run unchanged
- Touch input simulation for capacitive-touch models
- Animation mode: `display.show()` called in a loop, streamed as frames to the browser
- More displays — the goal is coverage of the whole [waveshare.com/product/displays.htm](https://www.waveshare.com/product/displays.htm) catalog. PRs adding a `displays.json` entry are welcome.

## License

MIT for the code in this repo. Waveshare's product photos, if you add any under `backend/assets/photos/`, remain Waveshare's — don't redistribute them as part of your fork without checking their terms.
