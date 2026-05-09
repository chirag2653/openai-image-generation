# openai-image-generation

Skill that generates images with OpenAI's [`gpt-image-2`](https://developers.openai.com/api/docs/guides/image-generation) model — released April 21 2026, OpenAI's *"most capable image model."* Activates only on explicit "OpenAI" / "gpt-image" / `/openai-image` mentions.

## Install

```bash
npx skills add chirag2653/openai-image-generation -g -y
```

After install, the skill appears as `openai-image-generation` in your agent's skill list.

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

## What's Not Built (Yet)

- Image edits via `/v1/images/edits` (reference images, mask-based inpainting)
- Streaming partial images via `partial_images`

## Reference

- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- Prompting cookbook: https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
- Skill workflow + trigger rules: [`skills/openai-image-generation/SKILL.md`](skills/openai-image-generation/SKILL.md)
- Dev guide (for editing the skill): [`CLAUDE.md`](CLAUDE.md)
