#!/usr/bin/env python
"""
OpenAI Image Generation Script (gpt-image-2)

Generates images using OpenAI's GPT Image 2 model — released April 2026,
described in OpenAI's docs as "our most capable image model."

Usage (interactive / human-friendly):
    python openai_generate.py --prompt "..." [--output PATH] [options]

Usage (programmatic / agent-native):
    python openai_generate.py --prompt "..." --json [options]
        → suppresses the banner; emits a single JSON object on stdout.

If --output is omitted, the script writes to:
    outputs/openai-image-YYYYMMDD-HHMMSS.png  (relative to current working dir)

API Key (read-only — script never writes the key anywhere):
    Looks for OPENAI_API_KEY in this order:
      1. process env var OPENAI_API_KEY
      2. Windows User-scope env var (read via PowerShell, useful in IDEs that
         don't inherit User env vars — e.g. Cursor)
      3. .env.local in the current working directory
      4. .env in the current working directory

Exit codes:
    0  success — file(s) saved
    1  key missing OR openai SDK not installed (stop and tell user how to fix)
    2  API call failed (e.g. quota, invalid prompt, moderation rejection) OR
       invalid parameters caught locally (--n < 1, --compression out of 0-100)
    3  API returned no images (transient — safe to retry once)

JSON mode output schema:
    Success: {"ok": true, "saved": [...], "key_source": "...",
              "model": "...", "size": "...", "quality": "...",
              "format": "...", "n": N, "prompt": "...",
              "cost_estimate_usd": float}
    Failure: {"ok": false, "error": "...", "exit_code": N}

Reference: https://developers.openai.com/api/docs/guides/image-generation
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows console defensiveness: re-encode stdout/stderr as UTF-8 so non-ASCII
# characters (em-dash, arrows, emoji, CJK, etc.) in prompts, output paths, or
# this script's docstring don't crash on cp1252 consoles. Falls back silently
# on older Python or when streams are already wrapped.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

# =============================================================================
# CONFIGURATION
# =============================================================================
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "auto"
DEFAULT_FORMAT = "png"
DEFAULT_N = 1
DEFAULT_OUTPUT_DIR = "outputs"
DEFAULT_OUTPUT_PREFIX = "openai-image"

VALID_SIZES_HINT = [
    "1024x1024", "1536x1024", "1024x1536",
    "2048x2048", "2048x1152",
    "3840x2160", "2160x3840",
    "auto",
]
VALID_QUALITIES = {"low", "medium", "high", "auto"}
VALID_FORMATS = {"png", "jpeg", "webp"}

# Approximate USD cost per image at 1024x1024 (OpenAI public pricing).
# Scaled by area ratio for non-square sizes. "auto" estimated as medium.
COST_TABLE = {"low": 0.006, "medium": 0.053, "high": 0.211, "auto": 0.053}


def estimate_cost(size: str, quality: str, n: int) -> float:
    """Estimate USD cost for size/quality/n. Best-effort — actual billing
    may differ slightly. Returned as a float rounded to 4 decimals."""
    base = COST_TABLE.get(quality, 0.053)
    if size == "auto":
        area_ratio = 1.0
    else:
        try:
            w_str, h_str = size.lower().split("x")
            w, h = int(w_str), int(h_str)
            area_ratio = (w * h) / (1024 * 1024)
        except (ValueError, AttributeError):
            area_ratio = 1.0
    return round(base * area_ratio * n, 4)


# =============================================================================
# DEFAULT FILENAME
# =============================================================================
def default_output_path(fmt: str) -> Path:
    """Build the default output path: outputs/openai-image-YYYYMMDD-HHMMSS.<ext>

    Resolved relative to the current working directory (i.e. wherever the user
    invoked the script from). The `outputs/` dir is created on save.
    """
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = "jpg" if fmt == "jpeg" else fmt
    return Path(DEFAULT_OUTPUT_DIR) / f"{DEFAULT_OUTPUT_PREFIX}-{timestamp}.{ext}"


# =============================================================================
# API KEY LOADING (4-tier loader — read-only, never writes)
# =============================================================================
def _read_windows_user_env(var_name: str) -> str | None:
    """Read a Windows User/Machine-scope env var via PowerShell.

    Useful for IDEs like Cursor that launch from a parent process predating
    the variable being set, so they don't inherit it through normal env.
    """
    if sys.platform != "win32":
        return None
    if not shutil.which("powershell"):
        return None
    try:
        for scope in ("User", "Machine"):
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"[System.Environment]::GetEnvironmentVariable('{var_name}', '{scope}')",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            value = (result.stdout or "").strip()
            if value:
                return value
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def _read_dotenv_value(path: Path, var_name: str) -> str | None:
    """Lightweight .env reader (no dependency). Returns the value of var_name
    or None if the file doesn't exist or doesn't define it.
    """
    if not path.exists():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == var_name:
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def load_api_key() -> tuple[str | None, str | None]:
    """Returns (key, source_label). source_label is for logging only."""
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"], "process env"

    win_key = _read_windows_user_env("OPENAI_API_KEY")
    if win_key:
        return win_key, "Windows User env"

    cwd = Path.cwd()
    for filename in (".env.local", ".env"):
        value = _read_dotenv_value(cwd / filename, "OPENAI_API_KEY")
        if value:
            return value, f"{filename} (cwd)"

    return None, None


# =============================================================================
# OUTPUT HELPERS (json-mode aware)
# =============================================================================
def info(message: str, json_mode: bool) -> None:
    """Informational message — stderr in json mode (so stdout stays clean
    for the final JSON object), stdout otherwise."""
    print(message, file=(sys.stderr if json_mode else sys.stdout))


def emit_error(message: str, exit_code: int, json_mode: bool) -> int:
    """Emit an error consistently in both modes; returns the exit code."""
    if json_mode:
        print(json.dumps({"ok": False, "error": message, "exit_code": exit_code}))
    print(f"ERROR: {message}", file=sys.stderr)
    return exit_code


# =============================================================================
# ARGUMENT PARSING
# =============================================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate images with OpenAI gpt-image-2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--prompt", "-p", required=True,
                        help="Text prompt describing the image")
    parser.add_argument("--output", "-o", default=None,
                        help=(f"Output file path. If omitted, defaults to "
                              f"{DEFAULT_OUTPUT_DIR}/{DEFAULT_OUTPUT_PREFIX}-"
                              f"YYYYMMDD-HHMMSS.<ext> in the current dir."))
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Model id (default: {DEFAULT_MODEL})")
    parser.add_argument("--size", default=DEFAULT_SIZE,
                        help=(f"WIDTHxHEIGHT or 'auto' (default: {DEFAULT_SIZE}). "
                              f"Common: {', '.join(VALID_SIZES_HINT[:5])}. "
                              "Constraints: max edge 3840px, both edges multiples of 16, "
                              "aspect ratio <= 3:1, total pixels in [655,360 - 8,294,400]."))
    parser.add_argument("--quality", default=DEFAULT_QUALITY, choices=sorted(VALID_QUALITIES),
                        help=f"Render quality (default: {DEFAULT_QUALITY})")
    parser.add_argument("--n", type=int, default=DEFAULT_N,
                        help=f"Number of images to generate (default: {DEFAULT_N})")
    parser.add_argument("--format", default=DEFAULT_FORMAT, choices=sorted(VALID_FORMATS),
                        help=f"Output format (default: {DEFAULT_FORMAT})")
    parser.add_argument("--compression", type=int, default=None,
                        help="Output compression 0-100 (jpeg/webp only)")
    parser.add_argument("--background", default=None, choices=["auto", "opaque"],
                        help="Background mode (gpt-image-2 doesn't support transparent)")
    parser.add_argument("--moderation", default=None, choices=["auto", "low"],
                        help="Moderation strictness (default: auto)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Emit a single JSON object to stdout instead of the "
                             "human banner. Use for programmatic / agent invocation. "
                             "Informational logs go to stderr in this mode.")
    return parser.parse_args()


# =============================================================================
# MAIN
# =============================================================================
def main() -> int:
    args = parse_args()
    json_mode = args.json_output

    # Validate parameters that argparse can't express (cheap, fail fast before
    # spending an API call). Mapped to exit code 2 — "invalid request".
    if args.n < 1:
        return emit_error(f"--n must be >= 1 (got {args.n}).", 2, json_mode)
    if args.compression is not None and not (0 <= args.compression <= 100):
        return emit_error(
            f"--compression must be between 0 and 100 (got {args.compression}).",
            2, json_mode,
        )

    # Resolve output path (default if not provided)
    output_path = Path(args.output) if args.output else default_output_path(args.format)

    # Load API key
    api_key, key_source = load_api_key()
    if not api_key:
        if not json_mode:
            print("ERROR: OPENAI_API_KEY not found.\n", file=sys.stderr)
            print("Looked in:", file=sys.stderr)
            print("  1. process env OPENAI_API_KEY", file=sys.stderr)
            print("  2. Windows User/Machine env (via PowerShell)", file=sys.stderr)
            print("  3. .env.local in cwd", file=sys.stderr)
            print("  4. .env in cwd", file=sys.stderr)
            print("\nFix options:", file=sys.stderr)
            print("  Option A — Add to .env.local in this folder:", file=sys.stderr)
            print("    OPENAI_API_KEY=sk-...", file=sys.stderr)
            print("  Option B — Set Windows User env var permanently (PowerShell):", file=sys.stderr)
            print("    [System.Environment]::SetEnvironmentVariable("
                  "'OPENAI_API_KEY','sk-...','User')", file=sys.stderr)
            print("    Then restart your terminal.", file=sys.stderr)
            return 1
        return emit_error(
            "OPENAI_API_KEY not found. Looked in: process env, Windows User/Machine env, "
            ".env.local in cwd, .env in cwd. Fix: set Windows User env var or add to .env.local.",
            1, json_mode,
        )

    # Lazy import — defer heavy SDK import until after key check
    try:
        from openai import OpenAI
    except ImportError:
        return emit_error(
            "'openai' package not installed. Run: pip install -r requirements.txt",
            1, json_mode,
        )

    # Build kwargs (only include optionals when set, so SDK uses its defaults)
    kwargs: dict = {
        "model": args.model,
        "prompt": args.prompt,
        "n": args.n,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.format,
    }
    if args.compression is not None:
        kwargs["output_compression"] = args.compression
    if args.background is not None:
        kwargs["background"] = args.background
    if args.moderation is not None:
        kwargs["moderation"] = args.moderation

    # Print human-friendly status banner (only in non-json mode)
    if not json_mode:
        print("=" * 60)
        print("OpenAI Image Generation (gpt-image-2)")
        print("=" * 60)
        print(f"Key source: {key_source}")
        print(f"Model:      {args.model}")
        print(f"Size:       {args.size}")
        print(f"Quality:    {args.quality}")
        print(f"Format:     {args.format}")
        print(f"N:          {args.n}")
        print(f"Output:     {output_path}{' (default)' if not args.output else ''}")
        prompt_preview = args.prompt if len(args.prompt) <= 80 else args.prompt[:77] + "..."
        print(f"Prompt:     {prompt_preview}")
        print("=" * 60)

    # Create output dir
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Call API
    info("Calling /v1/images/generations ...", json_mode)
    client = OpenAI(api_key=api_key)
    try:
        result = client.images.generate(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return emit_error(f"API call failed: {exc}", 2, json_mode)

    # Save image(s)
    images = result.data or []
    if not images:
        return emit_error("API returned no images.", 3, json_mode)

    saved: list[str] = []
    for idx, item in enumerate(images):
        b64 = getattr(item, "b64_json", None)
        if not b64:
            print(f"WARN: image #{idx} has no b64_json; skipping.", file=sys.stderr)
            continue
        target = output_path
        if len(images) > 1:
            stem, ext = output_path.stem, output_path.suffix
            target = output_path.with_name(f"{stem}_{idx + 1}{ext}")
        target.write_bytes(base64.b64decode(b64))
        saved.append(str(target))
        info(f"Saved: {target}  ({target.stat().st_size:,} bytes)", json_mode)

    if not saved:
        return emit_error("All images had empty b64_json; nothing saved.", 3, json_mode)

    # Final result
    if json_mode:
        print(json.dumps({
            "ok": True,
            "saved": saved,
            "key_source": key_source,
            "model": args.model,
            "size": args.size,
            "quality": args.quality,
            "format": args.format,
            "n": args.n,
            "prompt": args.prompt,
            "cost_estimate_usd": estimate_cost(args.size, args.quality, args.n),
        }))
    else:
        print("=" * 60)
        print("SUCCESS")
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
