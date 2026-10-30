import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestDataDir(unittest.TestCase):
    def test_runtime_files_follow_noc_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")  # does not exist yet
            code = (
                "import noc_web as w, os, json;"
                "print(json.dumps([w.SETTINGS_FILE, w.SERVERS_FILE, w.SMS_CONFIG_FILE, w.LOG_FILE, w.STATUS_FILE]))"
            )
            env = dict(os.environ, NOC_DATA_DIR=data)
            env.pop("SECRET_KEY", None)
            out = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(ROOT, "web"),
                                 env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            paths = __import__("json").loads(out.stdout.splitlines()[-1])
            for p in paths:
                self.assertEqual(os.path.dirname(p), data)
            # First-run credentials were written to the data dir, not the source tree
            self.assertTrue(os.path.isfile(os.path.join(data, "noc_settings.json")))


class TestContainerFiles(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_dockerfile_wiring(self):
        text = self.read("Dockerfile")
        for needle in ("NOC_DATA_DIR=/data", "VOLUME /data", "EXPOSE 8082", "iputils-ping",
                       "web/requirements.txt", 'CMD ["python", "web/noc_web.py"]'):
            self.assertIn(needle, text)

    def test_compose_matches_dockerfile(self):
        text = self.read("docker-compose.yml")
        self.assertIn("8082:8082", text)
        self.assertIn("/data", text)

    def test_dockerignore_keeps_secrets_out_of_image(self):
        text = self.read(".dockerignore")
        for name in ("web/noc_settings.json", "web/noc_servers.json", "web/noc_sms.json"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
