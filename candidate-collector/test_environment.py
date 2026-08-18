"""Tests for environment and configuration files."""

import plistlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class EnvironmentConfigTests(unittest.TestCase):
    def test_python_version_pinned_to_312(self) -> None:
        path = ROOT / ".python-version"
        self.assertTrue(path.is_file(), ".python-version should exist")
        content = path.read_text().strip()
        self.assertTrue(content.startswith("3.12"), f".python-version should pin 3.12, got {content}")

    def test_run_sh_uses_python312(self) -> None:
        path = ROOT / "run.sh"
        content = path.read_text()
        self.assertIn("python3.12", content, "run.sh should default to python3.12")
        self.assertIn("TTC_PYTHON", content, "run.sh should allow TTC_PYTHON override")

    def test_requirements_include_paddleocr(self) -> None:
        path = ROOT / "requirements.txt"
        content = path.read_text()
        self.assertIn("paddlepaddle", content)
        self.assertIn("paddleocr", content)
        self.assertIn("python_version", content, "paddlepaddle should have environment markers")

    def test_launch_agent_keeps_local_service_alive(self) -> None:
        path = ROOT / "launchd" / "com.ttc.candidate-collector.plist"
        self.assertTrue(path.is_file(), "launchd service template should exist")
        with path.open("rb") as handle:
            config = plistlib.load(handle)
        self.assertEqual(config["Label"], "com.ttc.candidate-collector")
        self.assertTrue(config["RunAtLoad"])
        self.assertTrue(config["KeepAlive"])
        self.assertEqual(config["WorkingDirectory"], "__ROOT__")
        arguments = config["ProgramArguments"]
        self.assertEqual(arguments[0], "__PYTHON__")
        self.assertIn("127.0.0.1", arguments)
        self.assertNotIn("0.0.0.0", arguments)
        self.assertEqual(config["EnvironmentVariables"]["PATH"], "__PATH__")
        self.assertEqual(config["StandardOutPath"], "__STDOUT__")
        self.assertEqual(config["StandardErrorPath"], "__STDERR__")
        self.assertNotIn("/Users/", path.read_text())

        installer = ROOT / "scripts" / "install_local_service.sh"
        self.assertTrue(installer.is_file(), "launchd installer should exist")
        installer_text = installer.read_text()
        self.assertIn("plutil -replace ProgramArguments.0", installer_text)
        self.assertIn("plutil -replace WorkingDirectory", installer_text)
        self.assertIn('chmod 700 "$LOG_DIR"', installer_text)
        self.assertIn('chmod 600 "$LOG_OUT" "$LOG_ERR"', installer_text)
        self.assertIn("launchctl bootstrap", installer_text)
        self.assertIn("launchctl kickstart", installer_text)


if __name__ == "__main__":
    unittest.main()
