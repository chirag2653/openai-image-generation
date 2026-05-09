# openai-image-generation — Dev Guide

## What This Skill Does

Generates images using OpenAI's `gpt-image-2` model (released April 21 2026 — OpenAI's *"most capable image model"*). Only activates when the user explicitly mentions "OpenAI", "gpt-image", or uses the `/openai-image` command. Supports size, quality, format, compression, background, moderation, and multi-image (`--n`) generation via `/v1/images/generations`.

**Visibility:** Private GitHub repo (`chirag2653/openai-image-generation`)
**Runtime deps:** `python` 3.10+, `openai>=1.55.0`, `OPENAI_API_KEY`

## Repo Layout

```
openai-image-generation/
├── .env.local                              ← OPENAI_API_KEY (gitignored, dev only)
├── .gitignore
├── CLAUDE.md                               ← you are here
├── README.md                               ← public-facing docs
├── outputs/                                ← generated test images (gitignored)
└── skills/
    └── openai-image-generation/            ← installable skill payload
        ├── SKILL.md                        ← agent-facing instructions + trigger rules
        ├── requirements.txt                ← Python deps (just `openai`)
        └── scripts/
            └── openai_generate.py          ← argument parsing, key loader, API call, image save
```

## Key Files to Edit

| File | Purpose |
|------|---------|
| `skills/openai-image-generation/SKILL.md` | Trigger rules, context-gathering workflow, parameter table, smart-defaults inference |
| `skills/openai-image-generation/scripts/openai_generate.py` | Argument parsing, 4-tier API key loader, OpenAI SDK call, b64 → file save |
| `skills/openai-image-generation/requirements.txt` | Python deps that ship with the skill |

## How the API Key Is Resolved

The script tries four sources in order (first hit wins):

1. Process env var `$env:OPENAI_API_KEY`
2. Windows User-scope env var read via PowerShell (works in IDEs like Cursor that don't inherit User env)
3. `.env.local` in the current working directory
4. `.env` in the current working directory

If none match, the script prints both fix options (`.env.local` recipe + `[System.Environment]::SetEnvironmentVariable` PowerShell recipe) and exits with code 1.

## How to Test

```bash
# One-time deps install
pip install -r skills/openai-image-generation/requirements.txt

# Syntax check
python -m py_compile skills/openai-image-generation/scripts/openai_generate.py

# Cheapest real run (~$0.006) — verifies default filename + key loader
python skills/openai-image-generation/scripts/openai_generate.py \
    --prompt "A simple yellow circle on a flat blue background" \
    --quality low

# Verify a non-default format + custom output
python skills/openai-image-generation/scripts/openai_generate.py \
    --prompt "tiny coffee app icon" --quality low \
    --format jpeg --compression 80 --output outputs/test.jpg
```

After any change to argument parsing, always re-test the no-`--output` path to confirm auto-naming still works.

## Deploy Workflow

```bash
# Edit files in skills/openai-image-generation/, then:
git add skills/ && git commit -m "..." && git push
rm -rf "$HOME/.agents/skills/openai-image-generation"
npx skills add chirag2653/openai-image-generation -g -y
```

## What Not to Do

- **Don't commit API keys.** `.env.local` is in `.gitignore` — keep it that way.
- **Don't put dev-only files inside `skills/openai-image-generation/`.** That folder ships on install — only `SKILL.md`, `scripts/`, and `requirements.txt` belong there.
- **Don't loosen the trigger rules.** The skill must NOT activate for generic "generate an image" requests — only for explicit "OpenAI" / "gpt-image" / `/openai-image`. Otherwise it'll fight with `gemini-image-generation` and any other image-gen skills.
- **Don't add `python-dotenv` to requirements.** The script implements its own lightweight `.env` reader to keep the dependency footprint to just `openai`.
- **Don't claim image-edits / reference-image support.** That's the `/v1/images/edits` endpoint, not built yet — keep the SKILL.md frontmatter honest.

## Reference

- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- OpenAI changelog (April 2026 release): https://developers.openai.com/api/docs/changelog
- Image generation cookbook: https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
