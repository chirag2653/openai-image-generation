#!/usr/bin/env python
"""Offline test suite for openai_generate.py.

Fully self-contained: no network, no real OPENAI_API_KEY, no `pytest`, and no
real `openai` SDK required. A fake `openai` module is injected via sys.modules
so the API-calling paths can be exercised deterministically. This is what CI
runs on every push.

Run from the repo root:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Load the module under test directly from its path in the skill payload.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "skills" / "openai-image-generation" / "scripts" / "openai_generate.py"

_spec = importlib.util.spec_from_file_location("openai_generate", _SCRIPT)
assert _spec and _spec.loader, f"cannot load module under test at {_SCRIPT}"
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


# ---------------------------------------------------------------------------
# Fake openai SDK — lets us drive images.generate without a key or network.
# ---------------------------------------------------------------------------
_PNG_BYTES = b"\x89PNG\r\n\x1a\nFAKEIMAGEDATA"


class _FakeImage:
    def __init__(self, b64: str | None):
        self.b64_json = b64


def _make_fake_openai(*, images=None, raise_exc=None):
    """Build a fake `openai` module whose OpenAI().images.generate() returns
    `images` (a list of _FakeImage), or raises `raise_exc` if given."""
    module = types.ModuleType("openai")

    class _FakeImagesAPI:
        def generate(self, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            data = [_FakeImage(base64.b64encode(_PNG_BYTES).decode())] if images is None else images
            return types.SimpleNamespace(data=data)

    class _FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.images = _FakeImagesAPI()

    module.OpenAI = _FakeOpenAI
    return module


def run_main(argv, *, env=None, fake_openai=None, cwd=None):
    """Invoke gen.main() with a controlled argv/env/cwd and (optionally) a fake
    openai module. Returns (exit_code, stdout_str, stderr_str)."""
    argv = ["openai_generate.py", *argv]
    env = {} if env is None else env
    out, err = io.StringIO(), io.StringIO()

    ctx = []
    ctx.append(mock.patch.object(sys, "argv", argv))
    ctx.append(mock.patch.dict(os.environ, env, clear=True))
    # Never let the real Windows env reader interfere with tests.
    ctx.append(mock.patch.object(gen, "_read_windows_user_env", return_value=None))
    if fake_openai is not None:
        ctx.append(mock.patch.dict(sys.modules, {"openai": fake_openai}))

    with contextlib.ExitStack() as stack:
        for c in ctx:
            stack.enter_context(c)
        if cwd is not None:
            stack.enter_context(_chdir(cwd))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gen.main()
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _chdir(path):
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------
class EstimateCostTests(unittest.TestCase):
    def test_low_square_single(self):
        self.assertEqual(gen.estimate_cost("1024x1024", "low", 1), 0.006)

    def test_high_square_single(self):
        self.assertEqual(gen.estimate_cost("1024x1024", "high", 1), 0.211)

    def test_auto_treated_as_medium(self):
        self.assertEqual(gen.estimate_cost("auto", "auto", 1), 0.053)

    def test_landscape_scales_by_area(self):
        # 1536x1024 == 1.5x the area of 1024x1024
        self.assertEqual(gen.estimate_cost("1536x1024", "low", 1), 0.009)

    def test_count_multiplies(self):
        self.assertEqual(gen.estimate_cost("1024x1024", "low", 3), 0.018)

    def test_unknown_quality_falls_back(self):
        self.assertEqual(gen.estimate_cost("1024x1024", "bogus", 1), 0.053)

    def test_malformed_size_uses_ratio_one(self):
        self.assertEqual(gen.estimate_cost("notasize", "low", 1), 0.006)


class DefaultOutputPathTests(unittest.TestCase):
    def test_png_extension_and_prefix(self):
        p = gen.default_output_path("png")
        self.assertEqual(p.parts[0], "outputs")
        self.assertEqual(p.suffix, ".png")
        self.assertTrue(p.name.startswith("openai-image-"))

    def test_jpeg_maps_to_jpg(self):
        self.assertEqual(gen.default_output_path("jpeg").suffix, ".jpg")

    def test_webp_extension(self):
        self.assertEqual(gen.default_output_path("webp").suffix, ".webp")


class DotenvReaderTests(unittest.TestCase):
    def _write(self, text):
        f = Path(self.tmp.name) / ".env.local"
        f.write_text(text, encoding="utf-8")
        return f

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_double_quoted_value(self):
        f = self._write('OPENAI_API_KEY="sk-abc123"\n')
        self.assertEqual(gen._read_dotenv_value(f, "OPENAI_API_KEY"), "sk-abc123")

    def test_single_quoted_value(self):
        f = self._write("OPENAI_API_KEY='sk-xyz'\n")
        self.assertEqual(gen._read_dotenv_value(f, "OPENAI_API_KEY"), "sk-xyz")

    def test_unquoted_value_with_comments_and_blanks(self):
        f = self._write("# a comment\n\nOPENAI_API_KEY=sk-plain\n")
        self.assertEqual(gen._read_dotenv_value(f, "OPENAI_API_KEY"), "sk-plain")

    def test_missing_var_returns_none(self):
        f = self._write("OTHER=value\n")
        self.assertIsNone(gen._read_dotenv_value(f, "OPENAI_API_KEY"))

    def test_nonexistent_file_returns_none(self):
        missing = Path(self.tmp.name) / "nope.env"
        self.assertIsNone(gen._read_dotenv_value(missing, "OPENAI_API_KEY"))


class LoadApiKeyPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_process_env_wins(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}, clear=True):
            key, source = gen.load_api_key()
        self.assertEqual(key, "sk-env")
        self.assertEqual(source, "process env")

    def test_dotenv_local_used_when_env_absent(self):
        (Path(self.tmp.name) / ".env.local").write_text("OPENAI_API_KEY=sk-local\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(gen, "_read_windows_user_env", return_value=None), \
             _chdir(self.tmp.name):
            key, source = gen.load_api_key()
        self.assertEqual(key, "sk-local")
        self.assertIn(".env.local", source)

    def test_dotenv_local_precedes_plain_dotenv(self):
        (Path(self.tmp.name) / ".env.local").write_text("OPENAI_API_KEY=sk-local\n", encoding="utf-8")
        (Path(self.tmp.name) / ".env").write_text("OPENAI_API_KEY=sk-plain\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(gen, "_read_windows_user_env", return_value=None), \
             _chdir(self.tmp.name):
            key, _ = gen.load_api_key()
        self.assertEqual(key, "sk-local")

    def test_returns_none_when_nothing_found(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(gen, "_read_windows_user_env", return_value=None), \
             _chdir(self.tmp.name):
            key, source = gen.load_api_key()
        self.assertIsNone(key)
        self.assertIsNone(source)


class ArgParsingTests(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.object(sys, "argv", ["x", "--prompt", "hi"]):
            args = gen.parse_args()
        self.assertEqual(args.size, "1024x1024")
        self.assertEqual(args.quality, "auto")
        self.assertEqual(args.n, 1)
        self.assertEqual(args.format, "png")
        self.assertIsNone(args.output)
        self.assertFalse(args.json_output)

    def test_prompt_required(self):
        with mock.patch.object(sys, "argv", ["x"]), self.assertRaises(SystemExit):
            gen.parse_args()

    def test_invalid_quality_rejected(self):
        with mock.patch.object(sys, "argv", ["x", "--prompt", "hi", "--quality", "ultra"]), \
             self.assertRaises(SystemExit):
            gen.parse_args()


# ---------------------------------------------------------------------------
# main() integration tests (fake openai module)
# ---------------------------------------------------------------------------
class MainSuccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_json_success_writes_file_and_emits_schema(self):
        out_path = Path(self.tmp.name) / "img.png"
        code, stdout, stderr = run_main(
            ["--prompt", "yellow circle", "--quality", "low", "--output", str(out_path), "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
        )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.strip())  # stdout must be exactly one JSON object
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["saved"], [str(out_path)])
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertEqual(payload["cost_estimate_usd"], 0.006)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.read_bytes(), _PNG_BYTES)

    def test_default_output_path_when_omitted(self):
        code, stdout, _ = run_main(
            ["--prompt", "yellow circle", "--quality", "low", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
            cwd=self.tmp.name,
        )
        self.assertEqual(code, 0)
        saved = json.loads(stdout.strip())["saved"][0]
        self.assertTrue((Path(self.tmp.name) / saved).exists() or Path(saved).exists())
        self.assertIn("openai-image-", saved)

    def test_multi_image_naming(self):
        out_path = Path(self.tmp.name) / "icon.png"
        two = [_FakeImage(base64.b64encode(_PNG_BYTES).decode()) for _ in range(2)]
        code, stdout, _ = run_main(
            ["--prompt", "icon", "--n", "2", "--output", str(out_path), "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(images=two),
        )
        self.assertEqual(code, 0)
        saved = json.loads(stdout.strip())["saved"]
        self.assertEqual(len(saved), 2)
        self.assertTrue((Path(self.tmp.name) / "icon_1.png").exists())
        self.assertTrue((Path(self.tmp.name) / "icon_2.png").exists())

    def test_human_mode_prints_banner_not_json(self):
        out_path = Path(self.tmp.name) / "h.png"
        code, stdout, _ = run_main(
            ["--prompt", "yellow circle", "--quality", "low", "--output", str(out_path)],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
        )
        self.assertEqual(code, 0)
        self.assertIn("SUCCESS", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout.strip())


class MainFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_missing_key_exit_1(self):
        code, stdout, _ = run_main(
            ["--prompt", "hi", "--json"],
            env={},  # no key
            fake_openai=_make_fake_openai(),
            cwd=self.tmp.name,  # empty dir, no .env files
        )
        self.assertEqual(code, 1)
        payload = json.loads(stdout.strip())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["exit_code"], 1)

    def test_api_failure_exit_2(self):
        code, stdout, _ = run_main(
            ["--prompt", "hi", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(raise_exc=RuntimeError("boom")),
        )
        self.assertEqual(code, 2)
        payload = json.loads(stdout.strip())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["exit_code"], 2)
        self.assertIn("boom", payload["error"])

    def test_empty_images_exit_3(self):
        code, stdout, _ = run_main(
            ["--prompt", "hi", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(images=[]),
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout.strip())["exit_code"], 3)

    def test_all_empty_b64_exit_3(self):
        code, stdout, _ = run_main(
            ["--prompt", "hi", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(images=[_FakeImage(None)]),
        )
        self.assertEqual(code, 3)


class ValidationTests(unittest.TestCase):
    def test_n_zero_rejected_exit_2(self):
        code, stdout, _ = run_main(
            ["--prompt", "hi", "--n", "0", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
        )
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stdout.strip())["ok"])

    def test_negative_n_rejected_exit_2(self):
        code, _, _ = run_main(
            ["--prompt", "hi", "--n", "-3", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
        )
        self.assertEqual(code, 2)

    def test_compression_out_of_range_rejected_exit_2(self):
        code, _, _ = run_main(
            ["--prompt", "hi", "--compression", "150", "--format", "jpeg", "--json"],
            env={"OPENAI_API_KEY": "sk-test"},
            fake_openai=_make_fake_openai(),
        )
        self.assertEqual(code, 2)

    def test_compression_in_range_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "c.jpg"
            code, _, _ = run_main(
                ["--prompt", "hi", "--compression", "80", "--format", "jpeg",
                 "--output", str(out_path), "--json"],
                env={"OPENAI_API_KEY": "sk-test"},
                fake_openai=_make_fake_openai(),
            )
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
