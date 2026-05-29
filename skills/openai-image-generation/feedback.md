# Giving Feedback on This Skill

This skill is maintained openly. When a user wants to **report a bug, suggest an
improvement, or give feedback about THIS skill**, turn it into a GitHub issue on the
source repo so the maintainer can triage and ship a fix — which users then pick up via
the normal update path (`npx skills add chirag2653/openai-image-generation -g -y`, or
`/plugin marketplace update` for plugin installs).

**Source repo:** `chirag2653/openai-image-generation`

## When to run this flow

Triggers: "give feedback on this skill", "report a bug in the openai image skill",
"this skill did X wrong", "suggest an improvement for this skill", and similar.

Only for feedback about the **skill itself** (a broken command, a confusing step, a
missing capability, a docs error). **Not** for "I don't like this image" — that's a
prompt change, not a skill issue.

## Step 1 — Compose the issue (structured)

Build a short, reproducible title and body.

**Title:** one line, e.g. `[feedback] preflight passes but generate fails with 403`

**Body template:**

```
**What I was trying to do**
<one or two lines>

**What happened / what I'd suggest**
<the bug or the suggestion>

**Repro / context** (auto-collected)
- Skill: openai-image-generation
- OS: <Windows 11 / macOS 14 / Ubuntu 22.04 / ...>
- Python: <output of `$PY --version`>
- Install path: <`$dir` from the Script Location resolver>
- Command (if a run failed): <the exact command, prompt redacted>
- Exit code: <0/1/2/3, if relevant>
```

Collect OS, Python version, and `$dir` automatically — you already resolved `$PY` and
`$dir` during Step 0 of the main flow. Include the command + exit code only if the
feedback is about a failed run.

## Step 2 — PRIVACY GATE (non-negotiable)

Before sending **anything**, show the user the exact title + body and get explicit
confirmation. This goes to a **public** repo.

- **Redact by default:** the user's prompt text, file paths that reveal a
  project/client name, and — always — the API key and `key_source`. Never include them.
- If the prompt itself is essential to the bug, ask whether to include a sanitized
  version.
- If the user declines or hesitates, **stop and write nothing.**

## Step 3 — Submit (try `gh`, then fall back to a URL)

Anyone can open an issue on a public repo, but GitHub requires authentication — there is
**no anonymous path**. Try in this order:

**A. `gh` CLI** (cleanest — if installed and authenticated):

```bash
gh issue create \
  --repo chirag2653/openai-image-generation \
  --title "TITLE" \
  --body "BODY" \
  --label user-feedback
```

On success `gh` prints the new issue URL — show it to the user.

**B. Pre-filled URL fallback** (works for anyone with a browser + a GitHub login):

If `gh` is missing or not authenticated, build a pre-filled new-issue URL and hand it to
the user to click, review, and submit:

```
https://github.com/chirag2653/openai-image-generation/issues/new?title=<url-encoded-title>&body=<url-encoded-body>&labels=user-feedback
```

URL-encode the title and body. The user lands on a pre-filled form, reviews it (a second
privacy checkpoint), and clicks **Submit new issue**.

## Notes

- **Label:** `user-feedback`. If `gh` errors that the label doesn't exist, retry without
  `--label` — the maintainer can label it on triage. On the URL path a non-existent
  label is silently dropped (harmless).
- **One issue per session.** If the user raises several points, fold them into a single
  issue rather than opening many.
- **Nothing is sent automatically.** Composing is silent, but submission always passes
  through the user — either `gh` on their own machine, or their click on the pre-filled
  form.
