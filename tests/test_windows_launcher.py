"""Exercise the Windows launcher with real venv/pip and offline wheel fixtures."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows batch launcher")
class WindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="modeltrace-launcher-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project = self.directory / "项目 with spaces (A&B)!"
        self.project.mkdir()
        self.launcher = self.project / "start.bat"
        if (PROJECT / "start.bat").exists():
            shutil.copyfile(PROJECT / "start.bat", self.launcher)
        self.requirements = self.project / "requirements.txt"
        self.requirements.write_text(
            "--find-links ./wheels\nlauncher-fixture>=1,<3\n", encoding="utf-8"
        )
        self.write_wheel("1.0")
        (self.project / "start.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from importlib.metadata import version\n"
            "Path('launched.json').write_text(json.dumps({\n"
            "    'executable': sys.executable, 'prefix': sys.prefix,\n"
            "    'cwd': str(Path.cwd()), 'version': version('launcher-fixture')\n"
            "}), encoding='utf-8')\n"
            "raise SystemExit(int(os.environ.get('LAUNCHER_FIXTURE_EXIT', '0')))\n",
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            self.environment.pop(key, None)
        self.environment.update(
            PIP_NO_INDEX="1",
            PIP_CONFIG_FILE=os.devnull,
            PIP_DISABLE_PIP_VERSION_CHECK="1",
            PYTHONIOENCODING="utf-8",
        )

    def write_wheel(self, version):
        wheels = self.project / "wheels"
        wheels.mkdir(exist_ok=True)
        metadata = f"launcher_fixture-{version}.dist-info"
        with zipfile.ZipFile(wheels / f"launcher_fixture-{version}-py3-none-any.whl", "w") as wheel:
            wheel.writestr("launcher_fixture.py", f"VERSION = {version!r}\n")
            wheel.writestr(
                f"{metadata}/METADATA",
                f"Metadata-Version: 2.1\nName: launcher-fixture\nVersion: {version}\n",
            )
            wheel.writestr(
                f"{metadata}/WHEEL",
                "Wheel-Version: 1.0\nGenerator: unittest\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            wheel.writestr(f"{metadata}/RECORD", "")

    def run_launcher(self, **overrides):
        self.assertTrue(self.launcher.is_file(), "The one-click start.bat launcher is missing")
        command_processor = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        # CMD strips the /s /c outer quotes; retain inner quotes around the batch path.
        command = f'"{command_processor}" /d /s /c ""{self.launcher}""'
        return subprocess.run(
            command,
            cwd=self.directory,
            env={**self.environment, **overrides},
            input="\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((self.project / "launched.json").read_text(encoding="utf-8"))

    def test_creates_environment_installs_dependencies_and_starts_from_project_directory(self):
        report = self.assert_success(self.run_launcher())

        self.assertEqual(Path(report["executable"]), self.project / ".venv" / "Scripts" / "python.exe")
        self.assertEqual(Path(report["prefix"]), self.project / ".venv")
        self.assertEqual(Path(report["cwd"]), self.project)
        self.assertEqual(report["version"], "1.0")

    def test_reuses_environment_without_system_python_and_upgrades_satisfied_dependency(self):
        self.assert_success(self.run_launcher())
        config = self.project / ".venv" / "pyvenv.cfg"
        original_config = (config.read_bytes(), config.stat().st_mtime_ns)
        self.write_wheel("2.0")

        report = self.assert_success(self.run_launcher(PATH=str(Path(os.environ["SystemRoot"]) / "System32")))

        self.assertEqual(report["version"], "2.0")
        self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), original_config)

    def test_dependency_failure_prevents_application_start(self):
        self.requirements.write_text("missing-modeltrace-launcher-fixture==1.0\n", encoding="utf-8")

        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / "launched.json").exists())
        self.assertIn("requirements.txt", result.stdout + result.stderr)

    def test_preserves_nonzero_application_exit_code(self):
        result = self.run_launcher(LAUNCHER_FIXTURE_EXIT="23")

        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue((self.project / "launched.json").exists())

    def test_external_pip_target_cannot_install_dependencies_outside_project_environment(self):
        external_target = self.directory / "external-target"

        result = self.run_launcher(PIP_TARGET=str(external_target))

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(external_target.exists(), "pip must not write dependencies outside .venv")
        self.assertFalse((self.project / "launched.json").exists())

    def test_external_pip_prefix_and_user_setting_cannot_redirect_project_dependencies(self):
        external_prefix = self.directory / "external-prefix"

        report = self.assert_success(self.run_launcher(PIP_PREFIX=str(external_prefix), PIP_USER="1"))

        self.assertEqual(Path(report["prefix"]), self.project / ".venv")
        self.assertEqual(report["version"], "1.0")
        self.assertFalse(external_prefix.exists())

    def test_external_pip_root_cannot_relocate_project_environment(self):
        external_root = self.directory / "external-root"

        report = self.assert_success(self.run_launcher(PIP_ROOT=str(external_root)))

        self.assertEqual(Path(report["prefix"]), self.project / ".venv")
        self.assertEqual(report["version"], "1.0")
        self.assertFalse(external_root.exists())

    def test_invalid_existing_environment_is_preserved(self):
        environment = self.project / ".venv"
        environment.mkdir()
        sentinel = environment / "keep.txt"
        sentinel.write_text("existing environment", encoding="utf-8")

        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing environment")
        self.assertIn(".venv", result.stdout + result.stderr)
        self.assertFalse((environment / "pyvenv.cfg").exists())
        self.assertFalse((self.project / "launched.json").exists())

    def test_missing_python_reports_failure_without_creating_environment(self):
        result = self.run_launcher(PATH=str(Path(os.environ["SystemRoot"]) / "System32"))

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / ".venv").exists())
        self.assertIn("Python", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
