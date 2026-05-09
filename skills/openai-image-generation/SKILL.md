---
name: openai-image-generation
description: Generate images using OpenAI's gpt-image-2 model (released April 2026, "OpenAI's most capable image model"). ONLY activates when user EXPLICITLY mentions 'OpenAI', 'gpt-image', or uses /openai-image command. Supports size, quality, format, and multi-image generation. Image edits / reference images via /v1/images/edits are not yet implemented.
---

# OpenAI Image Generation Skill

## Trigger Rules

**ONLY activate when user mentions:**
- "OpenAI" + image / "OpenAI image" / "use OpenAI"
- "gpt-image" / "gpt-image-2" / "GPT Image 2"
- `/openai-image` command

**DO NOT activate** for generic "generate an image" requests — let those go to the model the user has explicitly chosen, or ask which model they want.

---

## Context Gathering Flow

When the user invokes this skill, walk through these steps. Skip any step the user has already answered in their initial request.

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
    [--moderation auto|low]
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

The script auto-discovers `OPENAI_API_KEY` in this order:
1. Process env var `OPENAI_API_KEY`
2. Windows User-scope env var (read via PowerShell — works in IDEs like Cursor that don't inherit env vars)
3. `.env.local` in the current working directory
4. `.env` in the current working directory

**If missing**, the script prints both fix options:

```
Option A — Add to .env.local in your project folder:
  OPENAI_API_KEY=sk-...

Option B — Set Windows User env var permanently (PowerShell):
  [System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY','sk-...','User')
  Then restart your terminal.
```

Get your key from: https://platform.openai.com/settings/organization/api-keys

(GPT Image models also require API Organization Verification — if you get a 403, check verification status.)

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
