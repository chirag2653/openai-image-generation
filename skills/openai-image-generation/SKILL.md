---
name: openai-image-generation
description: Installable agent tool for generating images with OpenAI's gpt-image-2 model (April 2026 — OpenAI's most capable image model). Wraps a Python CLI that handles API auth, parameter validation, file I/O, and cost estimation — the agent composes one command with a prompt plus optional --size / --quality / --format / --n / --output flags and receives back saved file paths and a JSON metadata block (in --json mode). For any image task — logo, app icon, hero banner, social post, photo-realistic render, draft test, multi-variation set — the agent infers suitable parameters from task context and produces the artifact in a single subprocess call, then hands the saved path(s) to the next step. ACTIVATE when an image is needed AND OpenAI is the chosen provider — user mentions "OpenAI", "gpt-image", "gpt-image-2", invokes /openai-image, or a parent task has explicitly routed an image step here. DO NOT auto-trigger on generic "generate an image" requests with no provider specified — defer to whichever provider the user picks (other skills like gemini-image-generation cover the alternatives). Does NOT yet wrap /v1/images/edits (reference images, inpainting, image-to-image) — call the OpenAI API directly for those. Also activate to collect user feedback ABOUT this skill — phrases like "give feedback on the openai image skill" or "report a bug in this skill" — and file it as a GitHub issue (see feedback.md).
---

# OpenAI Image Generation Skill

## Tool Overview

This skill is a thin, reliable wrapper that lets an AI agent generate an image with OpenAI's gpt-image-2 in a single CLI call. The agent supplies the prompt and any parameters that matter for the task (size, quality, format, count, output path); the script handles API key discovery (4-tier loader: process env → Windows User env → `.env.local` → `.env`), validates and forwards the request to `POST /v1/images/generations`, decodes the returned base64 payload, writes the file(s) to disk, and — in `--json` mode — emits a single JSON line on stdout with the saved path(s), key source, and cost estimate. Distinct exit codes (`0` ok, `1` missing key/SDK, `2` API failure, `3` empty response) let the caller branch deterministically.

Practical recipe for an agent with task context (e.g. "I need a hero banner for the landing page"):
1. Pick parameters from the use case — see the smart-defaults table in Step 2.
2. Pick an output path — relative or absolute; parent dirs are auto-created.
3. Run the script with `--json`, parse the JSON, use `saved[0]` (or `saved[]` for n>1) downstream.

The skill is global (installed under `~/.agents/skills/openai-image-generation/` via `npx skills`, or under the plugin cache when installed as a Claude Code plugin — see [Script Location](#script-location--resolve-once-into-script-then-reuse-it)), so it's available across sessions and projects without per-project setup — the only requirement is an `OPENAI_API_KEY` discoverable from one of the four sources above. Image edits / reference images via `/v1/images/edits` are **not** wrapped here; for those, call the OpenAI API directly.

## Trigger Rules

**ONLY activate when user mentions:**
- "OpenAI" + image / "OpenAI image" / "use OpenAI"
- "gpt-image" / "gpt-image-2" / "GPT Image 2"
- `/openai-image` command

**DO NOT activate** for generic "generate an image" requests — let those go to the model the user has explicitly chosen, or ask which model they want.

---

## Context Gathering Flow

When the user invokes this skill, walk through these steps. Skip any step the user has already answered in their initial request.

### Step 0: First-Run Bootstrap (run FIRST, before any other work)

This skill is built to be **self-setting-up on a brand-new machine**. Before gathering context or composing a prompt, run the bootstrap so any gap surfaces as *setup* — never as a failed render after all the work is done. The whole sequence costs nothing (no image API call). The principle: **silently fix everything the skill can fix itself; ask the user only for the one thing it genuinely can't — the API key.**

**0a. Resolve the script path.** Run the resolver in [Script Location](#script-location--resolve-once-into-script-then-reuse-it) so `$SCRIPT` and `$dir` are set.

**0b. Find a working Python (≥3.10).** A fresh box may expose Python as `python`, `py -3`, or `python3` — and on Windows a bare `python` can be a Microsoft-Store shim that does nothing. Pick the first that actually prints a 3.10+ version, and reuse it as `$PY` everywhere below:

```bash
for c in "python" "py -3" "python3"; do
  v="$($c -c 'import sys;print(sys.version_info[:2]>=(3,10))' 2>/dev/null)"
  [ "$v" = "True" ] && PY="$c" && break
done
```

If none works, Python itself is missing or too old — this is the rare thing the skill can't install silently. Tell the user plainly (`Python 3.10+ isn't on PATH`) and point them to https://www.python.org/downloads/ (or `winget install Python.Python.3.12` on Windows), then stop until they confirm.

**0c. Run the no-cost pre-flight:**

```bash
$PY "$SCRIPT" --preflight --json
```

- **Exit `0`** → ready (`{"ok": true, "key_source": "...", "sdk": "<version>"}`). Proceed silently to Step 1 — say nothing about setup; it just works.
- **Exit `1`** → not ready. The JSON lists **every** missing prerequisite at once in `missing` (`"key"` and/or `"sdk"`) plus a `hint`. Resolve them in this order, then re-run `--preflight` to confirm:

  **If `"sdk"` is in `missing` → install it yourself, don't ask.** The `openai` SDK is a harmless, gitignored Python package — exactly the kind of thing the skill should fix on its own. Run:

  ```bash
  $PY "$SCRIPT" --install-deps --json
  ```

  This installs the bundled `requirements.txt` into **the same interpreter** (`sys.executable -m pip`), so it can't land in a different Python than the one that runs the script — the classic "I pip-installed it but it's still missing" trap. Exit `0` → installed (or already present); exit `1` → surface the pip error and fall back to telling the user to run `$PY -m pip install -r "$dir/requirements.txt"`.

  **If `"key"` is in `missing` → run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow.** This is the one prerequisite only the user can supply, so this is where you bring them into the loop with `AskUserQuestion`.

  **If both are missing → fix the SDK silently first, then ask for the key** — one clean setup pass, not two fail-and-retry cycles.

**0d. (Optional) Validate the key against the API** with a free `models.list()` call to catch an invalid key / unverified-org `403` *before* spending a paid generation:

```bash
$PY "$SCRIPT" --preflight --probe --json
```

> Throughout the rest of this doc commands are written as `python "$SCRIPT" ...` for brevity; on a machine where bare `python` isn't the right launcher, use the `$PY` you resolved in 0b instead.

### Step 1: Extract from User Input

Parse the user's request and pull out what you can:

| Field | Look for | Example input → extracted |
|-------|----------|---------------------------|
| **Prompt / Subject** | What to generate | "logo for my SaaS" → logo |
| **Style / Mood** | Style hints | "minimalist", "photorealistic", "watercolor" |
| **Colors** | Color mentions | "blue and white", "warm tones" |
| **Text in image** | Text to render | "with the word ACME", "say 'Hello'" |
| **Use Case** | Where it will be used | "for YouTube banner", "Instagram post", "print poster" |
| **Size** | Dimensions hints | "square", "1024x1024", "4K", "portrait", "landscape" |
| **Quality** | Speed-vs-fidelity hints | "draft", "quick test" → low; "final", "hero shot" → high |
| **Number** | How many | "3 variations", "5 options" |
| **Format** | File type | "png", "jpeg with 80% compression" |
| **Output Path** | Save location | "save to assets/logo.png" |

### Step 2: Infer Smart Defaults from Use Case

If the user didn't specify size/quality, infer from use case:

| Use case keywords | Size | Quality |
|-------------------|------|---------|
| logo, icon, avatar, profile pic | `1024x1024` | `medium` |
| hero, banner, header, cover | `1536x1024` | `high` |
| Instagram story, TikTok, Reels, vertical | `1024x1536` | `medium` |
| Instagram post, square ad | `1024x1024` | `medium` |
| draft, quick test, prototype, thumbnail | `1024x1024` | `low` |
| poster, flyer, print | `2048x2048` | `high` |
| 4K wallpaper, hero billboard | `3840x2160` | `high` |
| *no clear use case* | `1024x1024` | `auto` |

### Step 3: Default Output Filename

**If the user didn't specify `--output`**, the script auto-generates:

```
outputs/openai-image-YYYYMMDD-HHMMSS.png
```

(relative to the user's current working directory — the `outputs/` folder is created automatically). The `openai-image-` prefix makes the source obvious in any folder. Tell the user this default will be used unless they want a specific path.

### Step 4: Refine Prompt If Vague

If the user's prompt is under ~30 chars or vague (e.g. "a logo"), offer to refine it:

```
Your prompt is brief. I can enhance it for better results:

Original: "blue logo for my startup"
Refined:  "Modern minimalist logo for a tech startup, clean geometric
           shapes, gradient blue (#0066FF → #00AAFF) on transparent
           background, professional and confident aesthetic"

Use refined, original, or want to adjust further?
```

If the user's prompt is already detailed (30+ chars, clear intent), skip refinement.

### Step 5: Final Confirmation

Before generating, show **every parameter** that will be passed:

```
Ready to generate:

┌─────────────────────────────────────────────────────────────┐
│ OPENAI gpt-image-2 — CALL PARAMETERS                        │
├─────────────────────────────────────────────────────────────┤
│ 📝 Prompt:        [full prompt]                             │
│ 📏 Size:          [WxH or auto]                             │
│ ⚡ Quality:        [low/medium/high/auto]   Cost: ~$X.XXX   │
│ 🔢 N:             [number of images]                        │
│ 🖼️  Format:        [png/jpeg/webp]                          │
│ 🗜️  Compression:   [N/A or 0-100]                           │
│ 🎨 Background:    [auto/opaque]                             │
│ 🚦 Moderation:    [auto/low]                                │
│ 📁 Output:        [path]  ← (default) if auto-generated     │
└─────────────────────────────────────────────────────────────┘

Generate this image?
```

Cost reference (per image at 1024×1024): low $0.006 · medium $0.053 · high $0.211. For non-square sizes, multiply by ~1.5–2× for portrait/landscape at the same quality.

**For `low` quality drafts**, you can skip the confirmation block and just run.

---

## Execution

### Prerequisites (first run only)

The [Step 0 bootstrap](#step-0-first-run-bootstrap-run-first-before-any-other-work) handles all three automatically — this is what it's checking and how each gets resolved:

| Prerequisite | Who fixes it | How |
|--------------|--------------|-----|
| **Python 3.10+** on PATH | User (rare) | Detected in 0b. If missing, the skill can't self-install it — point the user at python.org / `winget` and wait. |
| **`openai` SDK** | **The skill, silently** | If preflight reports `sdk` missing, run `python "$SCRIPT" --install-deps` — installs into the same interpreter. No need to ask the user. |
| **`OPENAI_API_KEY`** | User (via `AskUserQuestion`) | The one prerequisite the skill genuinely can't self-provide. Run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow. |

> **Best practice:** verify everything with one no-cost call up front — `python "$SCRIPT" --preflight --json`. It reports key + SDK together, so a brand-new environment is one setup pass, not a string of mid-task failures.

### Script Location — resolve ONCE into `SCRIPT`, then reuse it

This skill ships through two channels that install to **different** locations, so **don't hardcode a path** — resolve it once and reuse `$SCRIPT`:

- **Claude Code plugin** (`/plugin install`) → bundled under the plugin cache, e.g. `~/.claude/plugins/cache/<plugin-id>/skills/openai-image-generation/`. Claude Code exposes the plugin's root as `$CLAUDE_PLUGIN_ROOT`.
- **`npx skills`** → `~/.agents/skills/openai-image-generation/` (with `~/.claude/skills/...` as a symlink to it).

Run this resolver first (bash / Git Bash — the shell Claude Code uses on Windows):

```bash
dir="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/openai-image-generation}"
[ -d "$dir" ] || dir="$HOME/.agents/skills/openai-image-generation"
[ -d "$dir" ] || dir="$(find "$HOME/.claude/plugins/cache" -type d -path '*skills/openai-image-generation' 2>/dev/null | head -1)"
SCRIPT="$dir/scripts/openai_generate.py"
```

Every command below (and in the CLI Cookbook) uses `"$SCRIPT"` — run the resolver first so it's set.

### Run Command

```bash
python "$SCRIPT" \
    --prompt "FULL_PROMPT" \
    [--output "PATH"] \
    [--size "WIDTHxHEIGHT"] \
    [--quality low|medium|high|auto] \
    [--n N] \
    [--format png|jpeg|webp] \
    [--compression 0-100] \
    [--background auto|opaque] \
    [--moderation auto|low] \
    [--json]

# No-cost setup modes (no --prompt, no API call) — run before generating:
python "$SCRIPT" --preflight [--probe] [--json]   # readiness check
python "$SCRIPT" --install-deps [--json]          # self-install the openai SDK
```

### Parameters

> **Only `--prompt` is required.** Everything else has defaults — pass only what you need to override.

| Flag | Required | Default | Notes |
|------|----------|---------|-------|
| `--prompt` / `-p` | ✅ | — | Full text prompt |
| `--output` / `-o` | ❌ | `outputs/openai-image-{timestamp}.png` | Auto-named if omitted |
| `--size` | ❌ | `1024x1024` | `WxH` or `auto`. Max edge 3840px, both edges multiples of 16, ratio ≤ 3:1, total pixels in [655,360 – 8,294,400] |
| `--quality` | ❌ | `auto` | `low` / `medium` / `high` / `auto` |
| `--n` | ❌ | `1` | Multiple images saved as `name_1.png`, `name_2.png`, … |
| `--format` | ❌ | `png` | `png` / `jpeg` / `webp` |
| `--compression` | ❌ | — | 0–100 (jpeg/webp only) |
| `--background` | ❌ | — | `auto` / `opaque` (gpt-image-2 doesn't support transparent) |
| `--moderation` | ❌ | `auto` | `auto` / `low` |
| `--json` | ❌ | off | Programmatic mode — emits a single JSON object on stdout instead of the human banner. Informational logs route to stderr. Use this when an agent calls the script. |
| `--preflight` | ❌ | off | No-cost readiness check (aliases: `--check`, `--doctor`). Reports API key + `openai` SDK status and exits `0` (ready) / `1` (not ready) — **no `--prompt` and no API call required**. See [Step 0](#step-0-first-run-bootstrap-run-first-before-any-other-work). |
| `--probe` | ❌ | off | With `--preflight`, also run an opt-in auth check via `models.list()` (a free call) to catch invalid keys / unverified-org `403`s before any paid generation. |
| `--install-deps` | ❌ | off | Self-bootstrap (alias `--setup`): install the bundled `requirements.txt` (the `openai` SDK) into **this** interpreter via `sys.executable -m pip`, then exit. No `--prompt`, no API call. Idempotent — no-op if the SDK is already present. Use this to auto-fix an `sdk`-missing pre-flight. |

---

## Agent Invocation Playbook

This script is designed to be called two ways. **Pick the mode that matches your situation.**

### Mode A — Autonomous (no human in the loop)

You're a parent agent calling this skill as a subroutine. Run the no-cost pre-flight once first to branch deterministically on setup before spending a generation, auto-install the SDK if it's the only gap, then run with `--json`:

```bash
python "$SCRIPT" --preflight --json        # exit 0 → ready
# exit 1 with "sdk" in missing → self-install, then re-check:
python "$SCRIPT" --install-deps --json && python "$SCRIPT" --preflight --json
# exit 1 with "key" in missing → can't self-fix headlessly; fail with the hint so
#   the orchestrator (or a human upstream) sets OPENAI_API_KEY, then retry.
python "$SCRIPT" --prompt "..." --quality low --json
```

- All informational output goes to **stderr**.
- **stdout** contains exactly one JSON object — parse it with `json.loads(stdout)`.
- Skip the ASCII confirmation block in Step 5; that ceremony is for human users.

### Mode B — Interactive (human in the loop)

Walk through Steps 1–5 of the Context Gathering Flow. Show the confirmation block. Run on user "yes". Don't pass `--json`.

### Exit Codes (both modes)

| Code | Meaning | Agent action |
|------|---------|--------------|
| `0` | Success — file(s) saved at returned paths (or, with `--preflight`, all prerequisites present; or, with `--install-deps`, the SDK installed/already present) | Use the saved paths |
| `1` | API key missing OR `openai` SDK not installed (with `--preflight`, one or more prerequisites missing — see `missing[]`; with `--install-deps`, the pip install failed) | **Stop and fix everything listed.** For a missing `sdk`, run `python "$SCRIPT" --install-deps` (auto-installs into this interpreter). For a missing `key`, run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow. The error/`missing` field reports **both** at once, so fix them together — SDK silently, key via `AskUserQuestion`. |
| `2` | API call failed (quota, invalid prompt, moderation rejection, network) **OR** invalid parameters caught locally (`--n < 1`, `--compression` outside 0–100) | Surface the error message verbatim. If it's a local validation error, fix the flag and re-run. Otherwise don't auto-retry — failure reasons differ. |
| `3` | API returned no images (rare, transient) | Safe to retry once with the same params. |

### `--json` Output Schema

**Success** (exit 0):
```json
{
  "ok": true,
  "saved": ["outputs/openai-image-20260509-150000.png"],
  "key_source": "Windows User env",
  "model": "gpt-image-2",
  "size": "1024x1024",
  "quality": "low",
  "format": "png",
  "n": 1,
  "prompt": "yellow circle on blue",
  "cost_estimate_usd": 0.006
}
```

**Failure** (exit 1, 2, or 3):
```json
{ "ok": false, "error": "<message>", "exit_code": 2 }
```

**Pre-flight** (`--preflight --json`):
```json
// exit 0 — ready
{ "ok": true, "key_source": "Windows User env", "sdk": "1.97.1" }

// exit 1 — not ready (lists EVERYTHING missing at once)
{ "ok": false, "missing": ["key", "sdk"], "key_source": null, "sdk": null,
  "hint": "set OPENAI_API_KEY (e.g. add 'OPENAI_API_KEY=sk-...' to .env.local); pip install -r requirements.txt" }
```

With `--probe`, a `"probe"` field is added (`"ok"` or `"failed: <reason>"`); a failed probe adds `"probe"` to `missing` and yields exit `1`.

**Self-install** (`--install-deps --json`):
```json
// exit 0 — installed now
{ "ok": true, "installed": true, "sdk": "1.97.1" }
// exit 0 — was already present (no-op)
{ "ok": true, "installed": false, "detail": "openai SDK already present" }
// exit 1 — pip failed
{ "ok": false, "error": "pip install failed (exit 1). <tail>", "exit_code": 1 }
```

### Programmatic Invocation Example (Python)

```python
import json, subprocess
result = subprocess.run(
    ["python", SCRIPT, "--prompt", prompt, "--quality", "low", "--json"],
    capture_output=True, text=True,
)
if result.returncode == 0:
    data = json.loads(result.stdout)
    image_paths = data["saved"]            # list[str]
    cost = data["cost_estimate_usd"]
elif result.returncode == 1:
    raise RuntimeError("OpenAI API key missing — ask the user to configure it.")
else:
    err = json.loads(result.stdout) if result.stdout else {}
    raise RuntimeError(err.get("error", result.stderr))
```

### Cross-Platform Script Path

Resolve `SCRIPT` once with the resolver in [Script Location](#script-location--resolve-once-into-script-then-reuse-it), then pass `"$SCRIPT"` — it already holds the absolute path for whichever install mode is in play, so you never type the install dir by hand.

PowerShell equivalent of the resolver:

```powershell
$dir = if ($env:CLAUDE_PLUGIN_ROOT) { "$env:CLAUDE_PLUGIN_ROOT\skills\openai-image-generation" } else { "$env:USERPROFILE\.agents\skills\openai-image-generation" }
$SCRIPT = "$dir\scripts\openai_generate.py"
```

> ⚠️ **Don't mix shell idioms.** `$env:USERPROFILE` expands only in PowerShell; in bash / Git Bash it collapses to a literal `:USERPROFILE\...` and Python fails with a cryptic `[Errno 22] Invalid argument`. Use the bash resolver in a bash shell and the PowerShell resolver in PowerShell — both set `SCRIPT` to a quoted absolute path that works regardless of cwd.

---

## CLI Cookbook

Copy-pasteable invocations for the most common scenarios. `SCRIPT` is set by the resolver in [Script Location](#script-location--resolve-once-into-script-then-reuse-it) — run it first, then reuse `"$SCRIPT"`. Only `--prompt` is required; everything else has defaults.

```bash
# Cheapest test (~$0.006) — verify setup with a throwaway image
python "$SCRIPT" --prompt "yellow circle on blue background" --quality low

# Logo (medium quality, default 1024×1024 png)
python "$SCRIPT" --prompt "Modern minimalist logo for AcmeAI, blue geometric gradient" \
    --quality medium

# Hero banner (landscape, high quality, custom save path)
python "$SCRIPT" --prompt "Cinematic mountain valley at sunrise, golden light" \
    --size 1536x1024 --quality high --output assets/hero.png

# Multiple variations in one call (saved as icon_1.png, icon_2.png, icon_3.png)
python "$SCRIPT" --prompt "App icon for a meditation app, soft gradients" \
    --n 3 --output outputs/icon.png

# Web-ready compressed JPEG
python "$SCRIPT" --prompt "Hero photo of a coffee cup on a wooden desk" \
    --format jpeg --compression 75 --output public/img/hero.jpg
```

**Path control:** `--output` accepts any relative or absolute path; parent directories are auto-created. For `--n > 1`, the script inserts `_1`, `_2`, … before the extension. If `--output` is omitted, the file lands at `outputs/openai-image-{timestamp}.{ext}` in the current working directory.

---

## API Key

The script auto-discovers `OPENAI_API_KEY` in this order (first hit wins) and **never writes the key anywhere** — it only reads:

1. Process env var `OPENAI_API_KEY`
2. Windows User/Machine-scope env var (read via PowerShell — works in IDEs like Cursor that don't inherit env vars set after launch)
3. `.env.local` in the current working directory
4. `.env` in the current working directory

Get a key from: https://platform.openai.com/settings/organization/api-keys
(GPT Image models also require API **Organization Verification** — if you get a 403, that's usually the cause; check verification status.)

### Missing API Key — Conversational Recovery

When the script exits with code `1` because no key was found, **do not fail silently and do not invent a key.** The API key is the one thing the skill can't self-install, so this is where you put the user in control — use the **`AskUserQuestion` tool** so they pick from clear options rather than parsing prose.

**1. State plainly what happened**, including *where* you looked (so they trust the search was real):

> I couldn't find your `OPENAI_API_KEY` anywhere — not in this shell's environment, not in the Windows User/Machine env vars, and not in a `.env.local` or `.env` in the folder I'm running from (`<cwd>`). How would you like to provide it?

**2. Ask with `AskUserQuestion`.** One question, header `"API key"`, with these four options (this ordering puts the most private, most reusable choices first and the transcript-exposing one last, with its warning inline):

| Option label | What you (the agent) do | Key in transcript? | Persistence |
|--------------|-------------------------|--------------------|-------------|
| **Set a permanent env var (recommended)** | Give them the one-liner below; they run it once and restart the terminal. You re-run after they confirm. | No | Permanent, all projects |
| **I'll create a `.env.local` myself** | They put `OPENAI_API_KEY=sk-...` in a `.env.local`/`.env` in this folder themselves; you don't see the key. Re-run when they say it's ready. | No | This project |
| **Paste it here, you save it to `.env.local`** | On their OK, you write `OPENAI_API_KEY=<key>` to `.env.local` in this folder (already gitignored). ⚠️ The key lands in this chat transcript. | **Yes** | This project |
| **Cancel** | Stop the image task; nothing is written. | — | — |

(`AskUserQuestion` always adds an "Other" escape hatch, so users can also point you at a key file or a different env var name.)

**3. Copy-paste recipes** to hand over for the first two options:

```powershell
# Permanent Windows User env var (run once, then restart the terminal):
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY','sk-...','User')
```

```bash
# macOS/Linux permanent (append to your shell rc, then restart the shell):
echo 'export OPENAI_API_KEY=sk-...' >> ~/.zshrc   # or ~/.bashrc

# Per-project — a .env.local in the working folder (gitignored). One line:
OPENAI_API_KEY=sk-...
```

**4. Rules of conduct (non-negotiable):**
- **Never write the key to a file unless the user explicitly chose the "paste it here" option.** When you do, write only to `.env.local` (gitignored) — never to a tracked file, and never `git add` it.
- **Never echo the key back** in chat after receiving it, and never put it in a commit, a log, or a `--json` field.
- If they pick a "set it yourself" option, just wait — re-run the same command (and `--preflight` to confirm) once they say the key is in place.
- A pasted key lives in the transcript permanently; if the user seems at all unsure, nudge them toward the env-var or self-created-`.env.local` options.
- Don't have them paste the key as a one-shot inline env var on the generate command — it scrolls into shell history and the transcript and doesn't persist. The options above are all better.

---

## Example Flows

### Flow A: Detailed request (no refinement, no asking)

**User:** "Use OpenAI to generate a photorealistic close-up of a vintage typewriter on a wooden desk with morning light, 1536x1024, high quality, save to assets/typewriter.png"

**Agent extracts:** prompt, size, quality, output path — all given. Skip refinement and inference.

**Agent shows confirmation block, runs on yes.**

### Flow B: Vague request (gather + refine)

**User:** "make me a logo with openai"

**Agent:** "What's the logo for? (company/app name, what does it do, any color preferences?)"

**User:** "AI automation agency called AutomateAI, modern, blue and silver"

**Agent:** Refines prompt → infers `1024x1024 medium` from "logo" → uses default output filename → shows confirmation block with full params + default output path → runs on yes.

### Flow C: Quick test

**User:** "/openai-image quick test of a yellow circle on blue background"

**Agent:** Detects "quick test" → `low` quality, `1024x1024`, default output filename. Optionally skip confirmation for `low` drafts and run directly.

---

## Giving feedback on this skill

This skill is maintained openly. If the user wants to report a bug, suggest an improvement, or give feedback **about the skill itself** (not about an image's content), turn it into a GitHub issue on the source repo (`chirag2653/openai-image-generation`) so it can be triaged and fixed — users then pick up the fix via the normal update path.

**Only on an explicit feedback request.** The full flow — compose a structured issue, run a privacy gate (never leak the prompt, file paths, or API key to a public repo), then submit via `gh` or a pre-filled-URL fallback — lives in [`feedback.md`](feedback.md) next to this file. Read it when feedback is requested.

---

## Reference

- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- Model: `gpt-image-2` (April 2026, OpenAI's *"most capable image model"*)
- Endpoint: `POST https://api.openai.com/v1/images/generations`
