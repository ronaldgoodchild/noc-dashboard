"""Run with: python -m unittest discover -s tests -v (requires Flask)."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "web" / "noc_web.py"


class WebCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "noc_web.py"
        shutil.copyfile(APP, self.script)
        # Synthetic credentials prevent import-time first-run generation. No user
        # settings or monitoring targets are loaded by these tests.
        (self.root / "noc_settings.json").write_text(json.dumps({
            "auth_user": "test-only", "auth_pass": "synthetic-test-password",
            "secret_key": "synthetic-test-secret", "port": 8123,
        }), encoding="utf-8")
        # Keep OS essentials for Windows subprocess startup, but omit app overrides.
        self.child_env = {key: value for key, value in os.environ.items()
                          if key not in {"NOC_PORT", "NOC_DATA_DIR", "SECRET_KEY", "SCAN_INTERVAL"}}
        with patch.dict(os.environ, self.child_env, clear=True):
            self.module = runpy.run_path(str(self.script))
        self.parse = self.module["_parse_bind_args"]
        self.globals = self.parse.__globals__

    def test_port_precedence_and_host(self):
        with patch.dict(os.environ, self.child_env, clear=True):
            self.assertEqual(self.parse([]).port, 8123)
            self.assertEqual(self.parse([]).host, "0.0.0.0")
            with patch.dict(os.environ, {"NOC_PORT": "8234"}):
                self.assertEqual(self.parse([]).port, 8234)
                args = self.parse(["--host", "127.0.0.1", "--port", "9000"])
                self.assertEqual((args.host, args.port), ("127.0.0.1", 9000))
            with patch.dict(self.globals, {"_cfg": {}}):
                self.assertEqual(self.parse([]).port, 8082)

    def test_invalid_ports_and_empty_host(self):
        for argv in (["--port", "0"], ["--port", "65536"], ["--port", "abc"],
                     ["--port", "1.5"], ["--host", " "]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.parse(argv)
                self.assertEqual(error.exception.code, 2)
        for port in ("1", "65535"):
            self.assertEqual(self.parse(["--port", port]).port, int(port))

    def test_invalid_environment_can_be_overridden(self):
        with patch.dict(os.environ, {"NOC_PORT": "bad"}):
            self.assertEqual(self.parse(["--port", "9000"]).port, 9000)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.parse([])
            self.assertEqual(error.exception.code, 2)

    def test_main_passes_options_to_flask_without_rewriting_settings(self):
        settings = self.root / "noc_settings.json"
        before = settings.read_bytes()
        args = self.parse(["--host", "127.0.0.1", "--port", "9000"])
        with patch.dict(self.globals, {"DATA_DIR": str(self.root)}), \
                patch.dict(self.globals, {"load_config": lambda: None, "load_sms_config": lambda: None,
                                         "log_event": lambda *args: None}), \
                patch.object(self.globals["threading"], "Thread") as scanner, \
                patch.object(self.globals["app"], "run") as run:
            self.module["main"](args)
            scanner.return_value.start.assert_called_once()
            run.assert_called_once_with(host="127.0.0.1", port=9000, debug=False, threaded=True)
        self.assertEqual(settings.read_bytes(), before)

    def test_real_help_and_invalid_args_do_not_create_runtime_files(self):
        (self.root / "noc_settings.json").unlink()
        for args, expected in [(["--help"], 0), (["--port", "bad"], 2), (["--unknown"], 2)]:
            result = subprocess.run([sys.executable, str(self.script), *args], env=self.child_env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected == 0:
                self.assertIn("--host", result.stdout)
                self.assertIn("--port", result.stdout)
            self.assertEqual(set(p.name for p in self.root.iterdir()), {"noc_web.py"})


if __name__ == "__main__":
    unittest.main()
