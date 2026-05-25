---
name: openai-image-generation
description: Installable agent tool for generating images with OpenAI's gpt-image-2 model (April 2026 — OpenAI's most capable image model). Wraps a Python CLI that handles API auth, parameter validation, file I/O, and cost estimation — the agent composes one command with a prompt plus optional --size / --quality / --format / --n / --output flags and receives back saved file paths and a JSON metadata block (in --json mode). For any image task — logo, app icon, hero banner, social post, photo-realistic render, draft test, multi-variation set — the agent infers suitable parameters from task context and produces the artifact in a single subprocess call, then hands the saved path(s) to the next step. ACTIVATE when an image is needed AND OpenAI is the chosen provider — user mentions "OpenAI", "gpt-image", "gpt-image-2", invokes /openai-image, or a parent task has explicitly routed an image step here. DO NOT auto-trigger on generic "generate an image" requests with no provider specified — defer to whichever provider the user picks (other skills like gemini-image-generation cover the alternatives). Does NOT yet wrap /v1/images/edits (reference images, inpainting, image-to-image) — call the OpenAI API directly for those.
---

# OpenAI Image Generation Skill

## Tool Overview

This skill is a thin, reliable wrapper that lets an AI agent generate an image with OpenAI's gpt-image-2 in a single CLI call. The agent supplies the prompt and any parameters that matter for the task (size, quality, format, count, output path); the script handles API key discovery (4-tier loader: process env → Windows User env → `.env.local` → `.env`), validates and forwards the request to `POST /v1/images/generations`, decodes the returned base64 payload, writes the file(s) to disk, and — in `--json` mode — emits a single JSON line on stdout with the saved path(s), key source, and cost estimate. Distinct exit codes (`0` ok, `1` missing key/SDK, `2` API failure, `3` empty response) let the caller branch deterministically.

Practical recipe for an agent with task context (e.g. "I need a hero banner for the landing page"):
1. Pick parameters from the use case — see the smart-defaults table in Step 2.
2. Pick an output path — relative or absolute; parent dirs are auto-created.
3. Run the script with `--json`, parse the JSON, use `saved[0]` (or `saved[]` for n>1) downstream.

The skill is global (lives at `~/.agents/skills/openai-image-generation/`), so it's available across sessions and projects without per-project setup — the only requirement is an `OPENAI_API_KEY` discoverable from one of the four sources above. Image edits / reference images via `/v1/images/edits` are **not** wrapped here; for those, call the OpenAI API directly.

## Trigger Rules

**ONLY activate when user mentions:**
- "OpenAI" + image / "OpenAI image" / "use OpenAI"
- "gpt-image" / "gpt-image-2" / "GPT Image 2"
- `/openai-image` command

**DO NOT activate** for generic "generate an image" requests — let those go to the model the user has explicitly chosen, or ask which model they want.

---

## Context Gathering Flow

When the user invokes this skill, walk through these steps. Skip any step the user has already answered in their initial request.

### Step 0: Pre-flight (run FIRST, before any other work)

Before gathering context or composing a prompt, run the **no-cost pre-flight** so a missing key or SDK surfaces as *setup*, not as a failed render after all the work is done. It costs nothing (no image API call) and never prompts:

```bash
python SCRIPT --preflight --json
```

- **Exit `0`** → ready (`{"ok": true, "key_source": "...", "sdk": "<version>"}`). Proceed to Step 1.
- **Exit `1`** → not ready. The JSON lists **every** missing prerequisite at once in `missing` (`"key"` and/or `"sdk"`) plus a `hint`. Resolve all of them before continuing:
  - `"key"` present in `missing` → run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow.
  - `"sdk"` present in `missing` → tell the user to `pip install -r "[SKILL_FOLDER]/requirements.txt"`.
  - Both present → guide both fixes together (one setup pass, not two fail-and-retry cycles), then re-run `--preflight` to confirm.

Optional: add `--probe` to also validate the key against the API (`models.list()`, a free call) and catch invalid keys / unverified-org `403`s *before* spending a paid generation:

```bash
python SCRIPT --preflight --probe --json
```

This reframes missing-key/SDK as setup that happens up front — never as a generation that errored.

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

- **Python 3.10+** on PATH.
- **`openai` SDK** — if the script exits `1` saying the package is missing, run `pip install -r "[SKILL_FOLDER]/requirements.txt"` (or `pip install "openai>=1.55.0"`), then re-run.
- **`OPENAI_API_KEY`** discoverable from one of the four sources in [API Key](#api-key). If absent, run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow.

> **Best practice:** verify both with a single no-cost call up front — `python SCRIPT --preflight --json` (see [Step 0: Pre-flight](#step-0-pre-flight-run-first-before-any-other-work)). It reports the key and SDK together, so a brand-new environment is one setup pass instead of two sequential `exit 1` failures.

### Script Location

```
[SKILL_FOLDER]/scripts/openai_generate.py
```

For Claude Code, the skill folder is typically:
- `~/.claude/skills/openai-image-generation/` (symlink)
- `~/.agents/skills/openai-image-generation/` (source)

### Run Command

```bash
python "[SKILL_FOLDER]/scripts/openai_generate.py" \
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

# No-cost pre-flight (no --prompt, no API call) — run before generating:
python "[SKILL_FOLDER]/scripts/openai_generate.py" --preflight [--probe] [--json]
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
| `--preflight` | ❌ | off | No-cost readiness check (aliases: `--check`, `--doctor`). Reports API key + `openai` SDK status and exits `0` (ready) / `1` (not ready) — **no `--prompt` and no API call required**. See [Step 0](#step-0-pre-flight-run-first-before-any-other-work). |
| `--probe` | ❌ | off | With `--preflight`, also run an opt-in auth check via `models.list()` (a free call) to catch invalid keys / unverified-org `403`s before any paid generation. |

---

## Agent Invocation Playbook

This script is designed to be called two ways. **Pick the mode that matches your situation.**

### Mode A — Autonomous (no human in the loop)

You're a parent agent calling this skill as a subroutine. Run the no-cost pre-flight once first to branch deterministically on setup before spending a generation, then run with `--json`:

```bash
python SCRIPT --preflight --json   # exit 0 → ready; exit 1 → fix what's in `missing`, then re-run
python SCRIPT --prompt "..." --quality low --json
```

- All informational output goes to **stderr**.
- **stdout** contains exactly one JSON object — parse it with `json.loads(stdout)`.
- Skip the ASCII confirmation block in Step 5; that ceremony is for human users.

### Mode B — Interactive (human in the loop)

Walk through Steps 1–5 of the Context Gathering Flow. Show the confirmation block. Run on user "yes". Don't pass `--json`.

### Exit Codes (both modes)

| Code | Meaning | Agent action |
|------|---------|--------------|
| `0` | Success — file(s) saved at returned paths (or, with `--preflight`, all prerequisites present) | Use the saved paths |
| `1` | API key missing OR `openai` SDK not installed (with `--preflight`, one or more prerequisites missing — see `missing[]`) | **Stop and fix everything listed.** Run the [Missing API Key — Conversational Recovery](#missing-api-key--conversational-recovery) flow if the key is missing, and `pip install -r requirements.txt` if the `openai` package is missing. The error/`missing` field reports **both** at once, so fix them together rather than one-at-a-time. |
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

**Default to the `~` form on every OS and shell:**

```
~/.agents/skills/openai-image-generation/scripts/openai_generate.py
```

`~` (and `$HOME`) expand in bash, Git Bash, zsh, **and** modern PowerShell, so this single form is the safest choice regardless of how the agent shells out. The skill source lives there (`~/.claude/skills/.../` is a symlink to it).

| Shell | Path form | Note |
|-------|-----------|------|
| bash / Git Bash / zsh (any OS, **incl. Windows**) | `~/.agents/skills/openai-image-generation/scripts/openai_generate.py` | `~` and `$HOME` both expand. **This is the shell Claude Code's Bash tool uses on Windows.** |
| PowerShell | `$HOME\.agents\skills\openai-image-generation\scripts\openai_generate.py` | `$env:USERPROFILE\...` also works *in PowerShell only*. Quote the path if the cwd has spaces. |

> ⚠️ **`$env:USERPROFILE` expands only in PowerShell.** In bash / Git Bash it does **not** expand — the path collapses to a literal `:USERPROFILE\...`, resolves against the cwd, and Python fails with a cryptic `[Errno 22] Invalid argument` *before* the script's own exit-code handling can run. If you're in any doubt about the shell, use the `~` form above — it works everywhere.

---

## CLI Cookbook

Copy-pasteable invocations for the most common scenarios. Replace `SCRIPT` with the actual script path (typically `~/.agents/skills/openai-image-generation/scripts/openai_generate.py`). Only `--prompt` is required; everything else has defaults.

```bash
# Cheapest test (~$0.006) — verify setup with a throwaway image
python SCRIPT --prompt "yellow circle on blue background" --quality low

# Logo (medium quality, default 1024×1024 png)
python SCRIPT --prompt "Modern minimalist logo for AcmeAI, blue geometric gradient" \
    --quality medium

# Hero banner (landscape, high quality, custom save path)
python SCRIPT --prompt "Cinematic mountain valley at sunrise, golden light" \
    --size 1536x1024 --quality high --output assets/hero.png

# Multiple variations in one call (saved as icon_1.png, icon_2.png, icon_3.png)
python SCRIPT --prompt "App icon for a meditation app, soft gradients" \
    --n 3 --output outputs/icon.png

# Web-ready compressed JPEG
python SCRIPT --prompt "Hero photo of a coffee cup on a wooden desk" \
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

When the script exits with code `1` because no key was found, **do not fail silently and do not invent a key.** Run this flow:

**1. State plainly what happened.** Something like:

> I couldn't find your `OPENAI_API_KEY` anywhere — not in this shell's environment, not in the Windows User/Machine env vars, and not in a `.env.local` or `.env` in the folder I'm running from (`<cwd>`). Here's how we can fix it:

**2. Offer three paths and let the user choose.** Make it explicit that **they don't have to paste the key into the chat** if they'd rather not:

| Option | What I (the agent) do | Key visible in chat? | Persistence |
|--------|----------------------|----------------------|-------------|
| **A — You paste it, I save it** | With your OK, I create a `.env.local` in this folder containing `OPENAI_API_KEY=<your key>`. It's already gitignored, so it won't be committed. | Yes — it lands in this transcript | Persists for this project |
| **B — You set it yourself** (key never touches chat) | You create the `.env.local` (or `.env`) yourself, or set the permanent Windows User env var (recipe below). Tell me when done and I'll re-run. | No | Persists |
| **C — Permanent, machine-wide** | You run the PowerShell one-liner below once, then restart the terminal. Best if you'll use this skill often. | No | Permanent (all projects) |

**3. Provide the copy-paste recipes:**

```powershell
# Option C — set the Windows User env var permanently (run once, then restart the terminal):
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY','sk-...','User')
```

```bash
# Option A/B — a .env.local in the working folder (gitignored). One line:
OPENAI_API_KEY=sk-...
```

**4. Rules of conduct:**
- **Never write the key to a file unless the user explicitly consents** (Option A). When you do, write only to `.env.local` (gitignored) — never to a tracked file, and never `git add` it.
- **Never echo the key back** in chat after receiving it, and never put it in a commit, a log, or a `--json` field.
- If the user picks Option B/C, just wait — re-run the same command once they confirm the key is in place.
- A pasted key lives in the transcript; if the user is uneasy about that, steer them to Option B or C.

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

## Reference

- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- Model: `gpt-image-2` (April 2026, OpenAI's *"most capable image model"*)
- Endpoint: `POST https://api.openai.com/v1/images/generations`
