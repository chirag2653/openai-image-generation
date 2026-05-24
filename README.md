# openai-image-generation

[![CI](https://github.com/chirag2653/openai-image-generation/actions/workflows/ci.yml/badge.svg)](https://github.com/chirag2653/openai-image-generation/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An installable [agent skill](https://github.com/obra/skills) that generates images with OpenAI's [`gpt-image-2`](https://developers.openai.com/api/docs/guides/image-generation) model — released April 21 2026, OpenAI's *"most capable image model."* It wraps a single, well-tested Python CLI so an AI agent (Claude Code, Cursor, Codex, etc.) can produce an image in one subprocess call and get back the saved path(s) plus a JSON metadata block.

The skill activates **only** on explicit "OpenAI" / "gpt-image" / `/openai-image` mentions, so it won't collide with other image-generation skills.

## Prerequisites

- **Python 3.10+** on your PATH
- An **`OPENAI_API_KEY`** ([get one here](https://platform.openai.com/settings/organization/api-keys)) — GPT Image models also require [API Organization Verification](https://help.openai.com/en/articles/10910291-api-organization-verification)
- The `openai` Python SDK (`pip install "openai>=1.55.0"`, or `pip install -r skills/openai-image-generation/requirements.txt`)

## Install

```bash
npx skills add chirag2653/openai-image-generation -g -y
```

After install, the skill appears as `openai-image-generation` in your agent's skill list. Only the `skills/openai-image-generation/` payload is copied onto your machine — the rest of this repo is project scaffolding.

## Usage (from inside an agent session)

> "Use OpenAI to generate a minimalist logo for AcmeCo, blue and silver, square"
>
> "/openai-image quick test of a yellow circle on a blue background"
>
> "Generate a 4K landscape hero banner with gpt-image-2: misty mountain at sunrise"

The skill will gather any missing context (size, quality, output path), show a confirmation block with full parameters and cost, then run.

## Manual Use (without the skill)

```bash
pip install -r skills/openai-image-generation/requirements.txt

python skills/openai-image-generation/scripts/openai_generate.py \
    --prompt "A yellow circle on blue background, flat illustration" \
    --quality low
```

The script auto-saves to `outputs/openai-image-YYYYMMDD-HHMMSS.png` if `--output` is omitted, and resolves `OPENAI_API_KEY` from the process env, Windows User env, `.env.local`, or `.env` (in that order).

## Available Knobs

| Flag | Required | Default | Notes |
|------|----------|---------|-------|
| `--prompt` / `-p` | ✅ | — | Text description |
| `--output` / `-o` | ❌ | `outputs/openai-image-{timestamp}.<ext>` | Auto-named if omitted |
| `--size` | ❌ | `1024x1024` | `WxH` or `auto`. Constraints: max edge ≤ 3840px, both edges multiples of 16, ratio ≤ 3:1, total pixels in [655,360 – 8,294,400] |
| `--quality` | ❌ | `auto` | `low` / `medium` / `high` / `auto` |
| `--n` | ❌ | `1` | Multi-image saves as `name_1.<ext>`, `name_2.<ext>`, … |
| `--format` | ❌ | `png` | `png` / `jpeg` / `webp` |
| `--compression` | ❌ | — | `0–100` (jpeg / webp only) |
| `--background` | ❌ | — | `auto` / `opaque` (gpt-image-2 doesn't support transparent) |
| `--moderation` | ❌ | `auto` | `auto` / `low` |
| `--model` | ❌ | `gpt-image-2` | Override only if you need a legacy model |

## Cost Reference

Per image at 1024×1024 (from the [official pricing](https://developers.openai.com/api/docs/guides/image-generation#calculating-costs)):

| Quality | Cost |
|---------|------|
| `low` | $0.006 |
| `medium` | $0.053 |
| `high` | $0.211 |

Larger non-square sizes scale roughly 1.5–2× at the same quality.

## API Key Resolution

The script reads `OPENAI_API_KEY` (and **never writes it**) from the first of these that's set:

1. Process env var `OPENAI_API_KEY`
2. Windows User/Machine-scope env var (read via PowerShell — handy for IDEs like Cursor that don't inherit env vars set after launch)
3. `.env.local` in the current working directory
4. `.env` in the current working directory

If none are found, the script exits with code `1` and prints how to fix it. Inside an agent session, the skill walks you through a recovery flow — including the option to **not** paste your key into the chat (set it yourself via `.env.local` or a Windows User env var).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Exit `1`, "OPENAI_API_KEY not found" | Set the key (see [API Key Resolution](#api-key-resolution)). Easiest persistent option on Windows: `[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY','sk-...','User')`, then restart the terminal. |
| Exit `1`, "'openai' package not installed" | `pip install "openai>=1.55.0"` |
| Exit `2` with a `403` | GPT Image models require API **Organization Verification** — verify your org in the OpenAI dashboard. |
| Exit `2`, "invalid parameters" | `--n` must be ≥ 1 and `--compression` must be 0–100. Fix the flag and re-run. |
| Exit `3` | Transient — the API returned no images. Safe to retry once. |

## Running the Tests

The repo ships a self-contained offline test suite (stdlib `unittest`, a fake `openai` SDK injected via `sys.modules` — **no API key, no network, no extra dependencies**). This is exactly what CI runs on every push:

```bash
python -m unittest discover -s tests -v
python -m py_compile skills/openai-image-generation/scripts/openai_generate.py
```

## What's Not Built (Yet)

- Image edits via `/v1/images/edits` (reference images, mask-based inpainting)
- Streaming partial images via `partial_images`

## License

[MIT](LICENSE) © Chirag Jain

## Reference

- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- Prompting cookbook: https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
- Skill workflow + trigger rules: [`skills/openai-image-generation/SKILL.md`](skills/openai-image-generation/SKILL.md)
- Dev guide (for editing/contributing to the skill): [`AGENTS.md`](AGENTS.md)
