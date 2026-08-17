export type DisplayFamily = "epaper" | "lcd" | "oled" | "char";

export interface DisplayCapabilities {
  mode: "1" | "L" | "RGB" | "P";
  colors: number;
  supports_color: boolean;
  shape: "rect" | "round";
}

export interface Display {
  id: string;
  name: string;
  family: DisplayFamily;
  resolution: [number, number];
  mode: "1" | "L" | "RGB" | "P";
  palette: string[] | null;
  shape?: "rect" | "round";
  char_grid?: [number, number];
  bezel: string;
  screen_bbox: [number, number, number, number];
  screen_rotation: number;
  canvas: [number, number];
  has_photo: boolean;
  capabilities: DisplayCapabilities;
  waveshare_url: string;
  /** Real Waveshare driver module/class this panel maps to (null = no portable vendor driver). */
  driver: string | null;
  /** Fidelity + vendor-API family, e.g. "epaper_7color", "lcd_rgb565", "oled_mono". */
  api: string;
  /** Ready-to-run vendor-API starter tailored to this panel (null when no portable driver). */
  device_snippet: string | null;
}

export interface Example {
  id: string;
  name: string;
  family: "any" | DisplayFamily;
  code: string;
  min_colors: number;
  shape: "any" | "rect" | "round";
}

export function exampleSupportsDisplay(ex: Example, d: Display): boolean {
  if (d.capabilities.colors < ex.min_colors) return false;
  if (ex.shape !== "any" && ex.shape !== d.capabilities.shape) return false;
  if (ex.family !== "any" && ex.family !== d.family) return false;
  return true;
}

// --- Claude Code integration ---

export interface ClaudeStatus {
  cli_installed: boolean;
  cli_version: string | null;
  authenticated: boolean;
  project_dir: string;
  project_dir_exists: boolean;
  email?: string | null;
  error?: string | null;
}

export interface LoginStart {
  session_id?: string;
  url?: string;
  error?: string;
}

export interface LoginResult {
  ok: boolean;
  email?: string | null;
  error?: string;
  output?: string;
  retryable?: boolean;
}

export interface AssistantBlock {
  type: "text" | "tool_use";
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  blocks: AssistantBlock[];
}

// --- Self-update ---

export interface UpdateStatus {
  in_git_repo: boolean;
  branch: string | null;
  local_sha: string | null;
  local_short: string | null;
  remote_sha: string | null;
  remote_short: string | null;
  behind: number;
  ahead: number;
  update_available: boolean;
  latest_commit_message: string | null;
  last_checked: number;
  error: string | null;
  can_apply: boolean;
}

export interface UpdateTriggerResult {
  ok: boolean;
  message?: string;
  log?: string;
  error?: string;
}


export interface RunResult {
  ok: boolean;
  stdout: string;
  stderr: string;
  friendly?: string | null;
  image_base64: string | null;
  duration_ms: number;
}
