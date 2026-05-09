#!/usr/bin/env python
"""
OpenAI Image Generation Script (gpt-image-2)

Generates images using OpenAI's GPT Image 2 model — released April 2026,
described in OpenAI's docs as "our most capable image model."

Usage:
    python openai_generate.py --prompt "..." [--output path/to/image.png] [options]

If --output is omitted, the script writes to:
    outputs/openai-image-YYYYMMDD-HHMMSS.png  (relative to current working dir)

API Key:
    Looks for OPENAI_API_KEY in this order:
      1. process env var OPENAI_API_KEY
      2. Windows User-scope env var (read via PowerShell, useful in IDEs that
         don't inherit User env vars — e.g. Cursor)
      3. .env.local in the current working directory
      4. .env in the current working directory

Reference: https://developers.openai.com/api/docs/guides/image-generation
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
# API KEY LOADING (3-tier loader, mirrors gemini-image-generation pattern)
# =============================================================================
def _read_windows_user_env(var_name: str) -> str | None:
    """Read a Windows User-scope env var via PowerShell.

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
    return parser.parse_args()


# =============================================================================
# MAIN
# =============================================================================
def main() -> int:
    args = parse_args()

    # Resolve output path (default if not provided)
    output_path = Path(args.output) if args.output else default_output_path(args.format)

    # Load API key
    api_key, key_source = load_api_key()
    if not api_key:
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

    # Lazy import — defer heavy SDK import until after key check
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: 'openai' package not installed. Run:", file=sys.stderr)
        print("  pip install -r requirements.txt", file=sys.stderr)
        print("  or: pip install openai", file=sys.stderr)
        return 1

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

    # Print status
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
    print("Calling /v1/images/generations ...")
    client = OpenAI(api_key=api_key)
    try:
        result = client.images.generate(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: API call failed: {exc}", file=sys.stderr)
        return 2

    # Save image(s)
    images = result.data or []
    if not images:
        print("ERROR: API returned no images.", file=sys.stderr)
        return 3

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
        print(f"Saved: {target}  ({target.stat().st_size:,} bytes)")

    if not saved:
        return 3

    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
