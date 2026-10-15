import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import codex_runner


COMPLETED_TURN_JSONL = '''\
{"type":"thread.started","thread_id":"019abcde-1234-7000-8000-123456789abc"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"reasoning","text":"Let me calculate."}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"stdout is not the final output file"}}
{"type":"turn.completed","usage":{"input_tokens":184,"cached_input_tokens":64,"output_tokens":37,"reasoning_tokens":12}}
'''


def version_result(version):
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=f"codex-cli {version}\n", stderr=""
    )


class RuntimeFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.versions = {}
        self.environment = self.enterContext(
            patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}, clear=True)
        )
        self.enterContext(patch("codex_runner._is_windows", return_value=True))
        self.which = self.enterContext(patch("codex_runner.shutil.which", return_value=None))
        self.run = self.enterContext(
            patch("codex_runner.subprocess.run", side_effect=self.run_process)
        )
        self.login_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Logged in using ChatGPT\n", stderr=""
        )

    def executable(self, relative, version="0.162.0-alpha.17.2"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        self.versions[str(path.resolve())] = version_result(version)
        return path

    def run_process(self, args, **kwargs):
        if args[1:] == ["--version"]:
            return self.versions[str(Path(args[0]).resolve())]
        if args[1:] == ["login", "status"]:
            return self.login_result
        raise AssertionError(f"Unexpected external command: {args}")

    def assert_runtime(self, runtime, executable, source, version):
        self.assertEqual(runtime.path, str(executable.resolve()))
        self.assertEqual(runtime.source, source)
        self.assertEqual(runtime.version, version)


class CodexDiscoveryTests(RuntimeFixtures):
    def test_explicit_path_wins_over_all_automatic_candidates(self):
        explicit = self.executable("manual/codex.exe", "0.150.0")
        environment = self.executable("environment/codex.exe", "0.160.0")
        self.executable("OpenAI/Codex/bin/new/codex.exe")
        os.environ["MODELTRACE_CODEX_PATH"] = str(environment)

        self.assert_runtime(
            codex_runner.discover_codex(str(explicit)), explicit, "manual", "0.150.0"
        )

    def test_environment_path_wins_when_no_explicit_path_is_given(self):
        environment = self.executable("environment/codex.exe", "0.150.0")
        self.executable("OpenAI/Codex/bin/new/codex.exe")
        os.environ["MODELTRACE_CODEX_PATH"] = str(environment)

        self.assert_runtime(
            codex_runner.discover_codex(), environment, "environment", "0.150.0"
        )

    def test_newest_valid_desktop_cli_is_selected(self):
        self.executable("OpenAI/Codex/bin/old/codex.exe", "0.138.0")
        newest = self.executable("OpenAI/Codex/bin/new/codex.exe")

        self.assert_runtime(
            codex_runner.discover_codex(), newest, "desktop", "0.162.0-alpha.17.2"
        )

    def test_program_install_precedes_path_lookup(self):
        installed = self.executable("Programs/OpenAI/Codex/bin/codex.exe", "0.138.0")
        self.which.return_value = str(self.executable("path/codex.exe"))

        self.assert_runtime(
            codex_runner.discover_codex(), installed, "install", "0.138.0"
        )


    def test_invalid_explicit_path_does_not_fall_back(self):
        missing = self.root / "missing/codex.exe"
        self.executable("OpenAI/Codex/bin/new/codex.exe")

        with self.assertRaises(codex_runner.CodexUnavailableError) as raised:
            codex_runner.discover_codex(str(missing))
        self.assertIn(str(missing), str(raised.exception))
        self.run.assert_not_called()

    def test_non_windows_platform_is_reported_as_unavailable(self):
        with patch("codex_runner._is_windows", return_value=False):
            with self.assertRaisesRegex(codex_runner.CodexUnavailableError, "Windows"):
                codex_runner.discover_codex()
        self.run.assert_not_called()

    def test_stale_environment_and_broken_desktop_candidate_are_skipped(self):
        os.environ["MODELTRACE_CODEX_PATH"] = str(self.root / "missing/codex.exe")
        broken = self.executable("OpenAI/Codex/bin/broken/codex.exe")
        self.versions[str(broken.resolve())] = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="failed"
        )
        good = self.executable("OpenAI/Codex/bin/good/codex.exe", "0.138.0")

        self.assert_runtime(codex_runner.discover_codex(), good, "desktop", "0.138.0")

    def test_path_lookup_is_used_when_install_is_stale(self):
        installed = self.executable("Programs/OpenAI/Codex/bin/codex.exe")
        self.versions[str(installed.resolve())] = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="failed"
        )
        executable = self.executable("path/codex.exe", "0.138.0")
        self.which.return_value = str(executable)

        self.assert_runtime(codex_runner.discover_codex(), executable, "path", "0.138.0")

    def test_stable_desktop_release_sorts_after_its_prerelease(self):
        self.executable("OpenAI/Codex/bin/alpha/codex.exe", "0.162.0-alpha.99.1")
        stable = self.executable("OpenAI/Codex/bin/stable/codex.exe", "0.162.0")

        self.assert_runtime(codex_runner.discover_codex(), stable, "desktop", "0.162.0")

    def test_desktop_prerelease_identifiers_follow_semantic_version_order(self):
        alpha = self.executable("OpenAI/Codex/bin/alpha/codex.exe", "0.162.0-alpha.99")
        beta = self.executable("OpenAI/Codex/bin/beta/codex.exe", "0.162.0-beta.1")
        os.utime(alpha, (200, 200))
        os.utime(beta, (100, 100))

        self.assert_runtime(codex_runner.discover_codex(), beta, "desktop", "0.162.0-beta.1")

    def test_desktop_build_metadata_is_ignored_for_version_precedence(self):
        older = self.executable("OpenAI/Codex/bin/older/codex.exe", "0.162.0")
        first_build = self.executable("OpenAI/Codex/bin/first/codex.exe", "0.163.0+build.99")
        newest_build = self.executable("OpenAI/Codex/bin/newest/codex.exe", "0.163.0+build.1")
        os.utime(older, (300, 300))
        os.utime(first_build, (100, 100))
        os.utime(newest_build, (200, 200))

        self.assert_runtime(
            codex_runner.discover_codex(), newest_build, "desktop", "0.163.0+build.1"
        )

    def test_unparsed_desktop_versions_fall_back_to_modification_time(self):
        old = self.executable("OpenAI/Codex/bin/old/codex.exe", "development-old")
        new = self.executable("OpenAI/Codex/bin/new/codex.exe", "development-new")
        os.utime(old, (100, 100))
        os.utime(new, (200, 200))

        self.assert_runtime(codex_runner.discover_codex(), new, "desktop", "development-new")

    def test_explicit_path_must_be_a_regular_codex_executable(self):
        wrong = self.executable("manual/other.exe")
        directory = self.root / "directory/codex.exe"
        directory.mkdir(parents=True)
        for path in (wrong, directory):
            with self.subTest(path=path):
                with self.assertRaises(codex_runner.CodexUnavailableError):
                    codex_runner.discover_codex(str(path))
        self.run.assert_not_called()

    def test_explicit_filename_is_case_insensitive_and_runtime_is_immutable(self):
        executable = self.executable("manual/CODEX.EXE", "0.138.0")
        runtime = codex_runner.discover_codex(str(executable))

        self.assert_runtime(runtime, executable, "manual", "0.138.0")
        with self.assertRaises(FrozenInstanceError):
            runtime.source = "path"
        self.run.assert_called_once_with(
            [str(executable.resolve()), "--version"], shell=False,
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )

    def test_failed_or_timed_out_manual_version_check_does_not_fall_back(self):
        executable = self.executable("manual/codex.exe")
        self.executable("OpenAI/Codex/bin/new/codex.exe")
        failures = [OSError("failed"), subprocess.TimeoutExpired(cmd=[], timeout=5)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("codex_runner.subprocess.run", side_effect=failure):
                    with self.assertRaises(codex_runner.CodexUnavailableError) as raised:
                        codex_runner.discover_codex(str(executable))
                self.assertIn(str(executable), str(raised.exception))

    def test_no_candidates_reports_unavailable(self):
        with self.assertRaisesRegex(codex_runner.CodexUnavailableError, "codex.exe"):
            codex_runner.discover_codex()


class CodexModelCatalogTests(RuntimeFixtures):
    def setUp(self):
        super().setUp()
        self.codex = self.executable("manual/codex.exe")
        self.catalog = {
            "models": [
                {
                    "slug": "deepseek-flash", "display_name": "DeepSeek Flash",
                    "visibility": "list",
                },
                {
                    "slug": "k3", "display_name": "K3", "visibility": "list",
                },
                {
                    "slug": "hidden-model", "display_name": "Hidden",
                    "visibility": "hide",
                },
            ]
        }

    def run_process(self, args, **kwargs):
        if args[1:3] == ["debug", "models"]:
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=json.dumps(self.catalog), stderr=""
            )
        return super().run_process(args, **kwargs)

    def test_user_config_catalog_returns_visible_custom_models(self):
        models = codex_runner.list_codex_models(str(self.codex), use_user_config=True)

        self.assertEqual(models, [
            {"id": "deepseek-flash", "label": "DeepSeek Flash"},
            {"id": "k3", "label": "K3"},
        ])
        self.assertEqual(self.run.call_args_list[-1].args[0], [
            str(self.codex.resolve()), "debug", "models",
        ])

    def test_isolated_catalog_uses_bundled_models(self):
        codex_runner.list_codex_models(str(self.codex), use_user_config=False)

        self.assertEqual(self.run.call_args_list[-1].args[0], [
            str(self.codex.resolve()), "debug", "models", "--bundled",
        ])

    def test_catalog_rejects_malformed_output(self):
        self.catalog = "not-a-model-catalog"

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "模型目录格式无效"):
            codex_runner.list_codex_models(str(self.codex), use_user_config=True)


class FakeCodexProcess:
    """Process boundary double; output files and adapter cleanup stay real."""

    def __init__(
        self, args, kwargs, *, answer, returncode, stdout, stderr, failure,
        missing_output, write_before_failure,
    ):
        self.args = args
        self.kwargs = kwargs
        self.answer = answer
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.failure = failure
        self.missing_output = missing_output
        self.write_before_failure = write_before_failure
        self.pid = 4321
        self.output_path = Path(args[args.index("--output-last-message") + 1])
        self.communications = []
        self.killed = False
        self.reaped = False

    def communicate(self, input=None, timeout=None):
        self.communications.append((input, timeout))
        if self.failure is not None and len(self.communications) == 1:
            if self.write_before_failure and not self.missing_output:
                self.output_path.write_text(self.answer, encoding="utf-8")
            raise self.failure
        if self.killed:
            self.reaped = True
        elif self.missing_output:
            self.output_path.unlink()
        else:
            self.output_path.write_text(self.answer, encoding="utf-8")
        return (self.stdout, self.stderr)

    def kill(self):
        self.killed = True


class CodexStatusTests(RuntimeFixtures):
    def test_status_reports_resolved_path_source_version_and_authentication(self):
        executable = self.executable("manual/codex.exe")

        self.assertEqual(codex_runner.get_codex_status(str(executable)), {
            "available": True,
            "authenticated": True,
            "path": str(executable.resolve()),
            "source": "manual",
            "version": "0.162.0-alpha.17.2",
        })
        self.run.assert_any_call(
            [str(executable.resolve()), "login", "status"], shell=False,
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )

    def test_status_reports_cli_that_is_present_but_not_authenticated(self):
        executable = self.executable("manual/codex.exe")
        self.login_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Not logged in"
        )

        status = codex_runner.get_codex_status(str(executable))

        self.assertTrue(status["available"])
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["path"], str(executable.resolve()))
        self.assertEqual(status["source"], "manual")
        self.assertEqual(status["version"], "0.162.0-alpha.17.2")
        self.assertRegex(status["error"], "[\u4e00-\u9fff]")

    def test_status_returns_structured_unavailable_result(self):
        self.assertEqual(codex_runner.get_codex_status(), {
            "available": False,
            "authenticated": False,
            "path": "",
            "source": "",
            "version": "",
            "error": "未找到 codex.exe",
        })

    def test_status_login_timeout_or_start_failure_retains_runtime_fields(self):
        executable = self.executable("manual/codex.exe")
        for failure in (OSError("secret"), subprocess.TimeoutExpired(cmd=[], timeout=5)):
            with self.subTest(failure=type(failure).__name__):
                self.run.side_effect = [version_result("0.162.0-alpha.17.2"), failure]
                status = codex_runner.get_codex_status(str(executable))
                self.assertTrue(status["available"])
                self.assertFalse(status["authenticated"])
                self.assertEqual(status["path"], str(executable.resolve()))
                self.assertEqual(status["source"], "manual")
                self.assertEqual(status["version"], "0.162.0-alpha.17.2")
                self.assertRegex(status["error"], "[\u4e00-\u9fff]")
                self.assertNotIn("secret", status["error"])

    def test_status_does_not_include_raw_authentication_output(self):
        executable = self.executable("manual/codex.exe")
        self.login_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="Bearer secret-token", stderr="api_key=secret"
        )

        status = codex_runner.get_codex_status(str(executable))

        self.assertFalse(status["authenticated"])
        self.assertNotIn("secret", str(status))
        self.assertNotIn("Bearer", str(status))

    def test_status_decoding_error_returns_structured_authentication_failure(self):
        executable = self.executable("manual/codex.exe")
        self.run.side_effect = [
            version_result("0.162.0-alpha.17.2"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
        ]

        status = codex_runner.get_codex_status(str(executable))

        self.assertTrue(status["available"])
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["path"], str(executable.resolve()))
        self.assertRegex(status["error"], "[\u4e00-\u9fff]")


class CodexExecutionTests(RuntimeFixtures):
    def setUp(self):
        super().setUp()
        self.codex = self.executable("manual/codex.exe")
        self.processes = []
        self.answer = "1, 2, 3\n"
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""
        self.failure = None
        self.start_failure = None
        self.missing_output = False
        self.write_before_failure = False
        self.taskkill_failure = None
        self.taskkill_calls = []
        self.output_paths = []
        self.popen = self.enterContext(
            patch("codex_runner.subprocess.Popen", side_effect=self.start_process)
        )

    def run_process(self, args, **kwargs):
        if args[0] == "taskkill":
            self.taskkill_calls.append((args, kwargs))
            if self.taskkill_failure is not None:
                raise self.taskkill_failure
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return super().run_process(args, **kwargs)

    def start_process(self, args, **kwargs):
        self.output_paths.append(Path(args[args.index("--output-last-message") + 1]))
        if self.start_failure is not None:
            raise self.start_failure
        process = FakeCodexProcess(
            args, kwargs, answer=self.answer, returncode=self.returncode,
            stdout=self.stdout, stderr=self.stderr, failure=self.failure,
            missing_output=self.missing_output,
            write_before_failure=self.write_before_failure,
        )
        self.processes.append(process)
        return process

    def request(self, model="gpt-6-astra", effort="low", timeout=120, use_user_config=False):
        return codex_runner.request_codex_completion(
            str(self.codex), model, effort, "challenge", timeout=timeout,
            use_user_config=use_user_config,
        )

    def request_result(self, **kwargs):
        request = getattr(codex_runner, "request_codex_completion_result", None)
        self.assertTrue(callable(request), "structured Codex completion entry point is missing")
        return request(str(self.codex), "gpt-6-astra", "low", "challenge", **kwargs)

    def assert_output_removed(self):
        self.assertTrue(self.output_paths)
        for path in self.output_paths:
            self.assertFalse(path.exists(), str(path))

    def test_exec_uses_fixed_safe_arguments_and_sends_prompt_on_stdin(self):
        self.request()
        process = self.processes[0]

        self.assertEqual(process.args, [
            str(self.codex.resolve()), "exec", "--json", "--ignore-user-config",
            "--model", "gpt-6-astra", "-c", 'model_reasoning_effort="low"',
            "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
            "--output-last-message", str(process.output_path), "-",
        ])
        self.assertEqual(process.kwargs, {
            "shell": False, "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8",
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        })
        self.assertEqual(process.communications, [("challenge", 120)])

    def test_exec_user_config_mode_omits_only_ignore_user_config(self):
        self.request(use_user_config=False)
        self.request(use_user_config=True)
        isolated_args = self.processes[0].args
        user_config_args = self.processes[1].args

        self.assertEqual(isolated_args.count("--ignore-user-config"), 1)
        self.assertNotIn("--ignore-user-config", user_config_args)
        isolated_args = isolated_args.copy()
        user_config_args = user_config_args.copy()
        isolated_args[isolated_args.index("--output-last-message") + 1] = "<output>"
        user_config_args[user_config_args.index("--output-last-message") + 1] = "<output>"
        isolated_args.remove("--ignore-user-config")
        self.assertEqual(isolated_args, user_config_args)

    def test_exec_reads_and_returns_output_last_message(self):
        self.assertEqual(self.request(), "1, 2, 3")

    def test_exec_rejects_unknown_reasoning_effort_before_starting_process(self):
        with self.assertRaises(ValueError):
            self.request(effort="ultra")
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_exec_rejects_empty_or_invalid_model_identifier(self):
        for model in ("", "model --danger", "a" * 129, "model\n", "model;$secret"):
            with self.subTest(model=model):
                with self.assertRaises(ValueError):
                    self.request(model=model)
        self.popen.assert_not_called()
        self.run.assert_not_called()

    def test_exec_maps_missing_login_to_authentication_error(self):
        self.login_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Not logged in"
        )

        with self.assertRaises(codex_runner.CodexAuthenticationError):
            self.request()
        self.popen.assert_not_called()

    def test_exec_maps_nonzero_exit_to_sanitized_execution_error(self):
        self.returncode = 1
        self.stderr = "initial startup warning " + "x" * 1500 + " actual final error"

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request()
        message = str(raised.exception)
        self.assertLessEqual(len(message), 1050)
        self.assertIn("actual final error", message)
        self.assertNotIn("initial startup warning", message)
        self.assert_output_removed()

    def test_exec_prefers_actual_structured_error_over_startup_warnings(self):
        self.returncode = 1
        wrapped_error = json.dumps(
            'tools.12: tool type "tool_search" is not supported'
        )
        self.stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps({"type": "error", "message": wrapped_error}),
            json.dumps({
                "type": "turn.failed",
                "error": {"message": wrapped_error},
            }),
        ])
        self.stderr = "plugin catalog warning"

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request()
        message = str(raised.exception)
        self.assertIn('tools.12: tool type "tool_search" is not supported', message)
        self.assertNotIn("plugin catalog warning", message)
        self.assert_output_removed()

    def test_exec_timeout_terminates_process_tree_and_removes_temporary_output(self):
        self.failure = subprocess.TimeoutExpired(cmd=["codex.exe"], timeout=120)

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "120"):
            self.request()
        self.assertEqual(self.taskkill_calls[0][0], ["taskkill", "/PID", "4321", "/T", "/F"])
        self.assertIs(self.taskkill_calls[0][1]["shell"], False)
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_exec_success_removes_temporary_output(self):
        self.answer = "  answer\n"

        self.assertEqual(self.request(), "answer")
        self.assert_output_removed()

    def test_exec_rejects_missing_or_empty_output_and_removes_file(self):
        for missing, answer in ((True, "unused"), (False, " \n\t")):
            with self.subTest(missing=missing):
                self.missing_output, self.answer = missing, answer
                with self.assertRaises(codex_runner.CodexExecutionError):
                    self.request()
                self.assert_output_removed()

    def test_exec_redacts_credentials_and_control_sequences_in_diagnostics(self):
        self.returncode = 1
        self.stdout = json.dumps(
            {
                "type": "error",
                "message": (
                    '\x1b[31mfailed\x1b[0m\napi_key=secret-key Bearer secret-bearer '
                    'token="secret-token" sk-secretvalue'
                ),
            }
        )
        self.stderr = "startup warning"

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request()
        message = str(raised.exception)
        self.assertIn("failed", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("\n", message)
        self.assert_output_removed()

    def test_exec_start_failure_maps_error_and_removes_output(self):
        self.start_failure = OSError("internal secret")

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request()
        self.assertNotIn("secret", str(raised.exception))
        self.assert_output_removed()

    def test_exec_timeout_falls_back_when_taskkill_fails(self):
        self.failure = subprocess.TimeoutExpired(cmd=[], timeout=120)
        self.taskkill_failure = OSError("missing taskkill")

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "120"):
            self.request()
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_exec_communicate_error_terminates_process_and_removes_output(self):
        self.failure = OSError("internal secret")

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request()
        self.assertNotIn("secret", str(raised.exception))
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_exec_supports_allowed_model_characters_efforts_and_custom_timeout(self):
        for effort in ("low", "medium", "high", "xhigh"):
            with self.subTest(effort=effort):
                self.assertEqual(self.request(model="provider/model:v1.2_test-3", effort=effort, timeout=17), "1, 2, 3")
                process = self.processes[-1]
                self.assertEqual(
                    process.args[process.args.index("--model") + 1],
                    "provider/model:v1.2_test-3",
                )
                self.assertEqual(
                    process.args[process.args.index("-c") + 1],
                    f'model_reasoning_effort="{effort}"',
                )
                self.assertEqual(process.communications, [("challenge", 17)])
                self.assert_output_removed()

    def test_exec_decoding_error_terminates_process_and_removes_output(self):
        self.failure = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

        with self.assertRaises(codex_runner.CodexExecutionError):
            self.request()
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_exec_taskkill_decoding_error_still_kills_and_reaps_process(self):
        self.failure = subprocess.TimeoutExpired(cmd=[], timeout=120)
        self.taskkill_failure = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "120"):
            self.request()
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_result_reads_final_file_and_completed_turn_usage(self):
        self.stdout = COMPLETED_TURN_JSONL
        self.answer = "  <final-answer>21</final-answer>\n"

        self.assertEqual(self.request_result(), {
            "text": "<final-answer>21</final-answer>",
            "usage": {"input_tokens": 184, "output_tokens": 37, "reasoning_tokens": 12},
        })
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.processes[0].communications, [("challenge", 600)])
        self.assert_output_removed()

    def test_result_does_not_infer_missing_reasoning_from_output_or_model_text(self):
        self.stdout = '''\
{"type":"thread.started","thread_id":"019abcde-1234-7000-8000-123456789abc"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I used 100 reasoning tokens."}}
{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":30}}
'''
        self.assertEqual(self.request_result()["usage"], {
            "input_tokens": 100, "output_tokens": 30, "reasoning_tokens": None,
        })

    def test_result_ignores_malformed_and_unrelated_jsonl_lines(self):
        self.stdout = '''\
not-json
{"type":"turn.completed","usage":
null
[]
42
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"answer"},"usage":{"input_tokens":999,"output_tokens":888}}
{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":0,"output_tokens":7}}
trailing noise
'''
        self.assertEqual(self.request_result()["usage"], {
            "input_tokens": 11, "output_tokens": 7, "reasoning_tokens": None,
        })

    def test_result_last_valid_usage_wins_without_accumulating_or_reusing_fields(self):
        self.stdout = COMPLETED_TURN_JSONL + '''\
{"type":"turn.completed","usage":{"input_tokens":25,"cached_input_tokens":0,"output_tokens":9}}
{"type":"turn.completed"}
{"type":"turn.completed","usage":null}
{"type":"turn.completed","usage":[]}
{"type":"turn.completed","usage":{}}
{"type":"turn.completed","usage":{"unrelated":99}}
'''
        self.assertEqual(self.request_result()["usage"], {
            "input_tokens": 25, "output_tokens": 9, "reasoning_tokens": None,
        })

    def test_result_preserves_null_and_real_zero_usage(self):
        for usage, expected in (
            ({"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
             {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}),
            ({"input_tokens": None, "output_tokens": None, "reasoning_tokens": None},
             {"input_tokens": None, "output_tokens": None, "reasoning_tokens": None}),
            ({"output_tokens": 8},
             {"input_tokens": None, "output_tokens": 8, "reasoning_tokens": None}),
        ):
            with self.subTest(usage=usage):
                self.stdout = json.dumps({"type": "turn.completed", "usage": usage})
                self.assertEqual(self.request_result()["usage"], expected)
                self.assert_output_removed()

    def test_result_all_invalid_or_null_counts_do_not_replace_previous_valid_usage(self):
        valid_turn = '{"type":"turn.completed","usage":{"input_tokens":42,"output_tokens":9}}\n'
        for invalid_usage in (
            {"input_tokens": "bad", "output_tokens": -1, "reasoning_tokens": True},
            {"input_tokens": None, "output_tokens": None, "reasoning_tokens": None},
            {"input_tokens": False, "output_tokens": 1.5, "reasoning_tokens": {}},
        ):
            with self.subTest(invalid_usage=invalid_usage):
                self.stdout = valid_turn + json.dumps({
                    "type": "turn.completed", "usage": invalid_usage,
                })
                self.assertEqual(self.request_result()["usage"], {
                    "input_tokens": 42, "output_tokens": 9, "reasoning_tokens": None,
                })
                self.assert_output_removed()

    def test_result_zero_count_replaces_previous_usage_without_retaining_other_fields(self):
        self.stdout = COMPLETED_TURN_JSONL + (
            '{"type":"turn.completed","usage":{"output_tokens":0}}\n'
        )
        self.assertEqual(self.request_result()["usage"], {
            "input_tokens": None, "output_tokens": 0, "reasoning_tokens": None,
        })
        self.assert_output_removed()

    def test_result_missing_or_invalid_usage_is_nullable(self):
        for stdout in ("", "not-json", '{"type":"turn.completed","usage":null}',
                       '{"type":"turn.completed","usage":"invalid"}'):
            with self.subTest(stdout=stdout):
                self.stdout = stdout
                self.assertEqual(self.request_result()["usage"], {
                    "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                })

    def test_result_rejects_invalid_token_counts_without_converting_them_to_zero(self):
        for count in (-1, 1.5, True, "12", [], {}):
            with self.subTest(count=count):
                self.stdout = json.dumps({"type": "turn.completed", "usage": {
                    "input_tokens": count, "output_tokens": count, "reasoning_tokens": count,
                }})
                self.assertEqual(self.request_result()["usage"], {
                    "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                })

    def test_result_rejects_missing_or_empty_final_file_even_with_valid_usage(self):
        self.stdout = COMPLETED_TURN_JSONL
        for missing, answer in ((True, "unused"), (False, " \n\t")):
            with self.subTest(missing=missing):
                self.missing_output, self.answer = missing, answer
                with self.assertRaises(codex_runner.CodexExecutionError):
                    self.request_result()
                self.assert_output_removed()

    def test_result_nonzero_exit_exposes_partial_answer_and_usage_as_typed_details(self):
        self.returncode = 1
        self.answer = "部分回答 api_key=answer-secret"
        self.stdout = COMPLETED_TURN_JSONL + (
            '{"type":"turn.failed","error":{"message":"上游失败"}}\n'
        )

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()

        self.assertEqual(raised.exception.details.text, self.answer)
        self.assertEqual(raised.exception.details.usage, {
            "input_tokens": 184, "output_tokens": 37, "reasoning_tokens": 12,
        })
        self.assert_output_removed()

    def test_result_empty_answer_exposes_available_usage_as_typed_details(self):
        self.answer = " \n\t"
        self.stdout = COMPLETED_TURN_JSONL

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()

        self.assertIsNone(raised.exception.details.text)
        self.assertEqual(raised.exception.details.usage, {
            "input_tokens": 184, "output_tokens": 37, "reasoning_tokens": 12,
        })
        self.assert_output_removed()

    def test_result_failure_without_answer_or_usage_exposes_empty_typed_details(self):
        self.returncode = 1
        self.answer = " \n\t"
        self.stdout = '{"type":"turn.failed","error":{"message":"上游失败"}}\n'

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()

        self.assertIsNone(raised.exception.details.text)
        self.assertIsNone(raised.exception.details.usage)
        self.assert_output_removed()

    def test_result_timeout_terminates_process_tree_and_removes_output(self):
        self.failure = subprocess.TimeoutExpired(cmd=["codex.exe"], timeout=600)

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "600"):
            self.request_result()
        self.assertEqual(self.taskkill_calls[0][0], ["taskkill", "/PID", "4321", "/T", "/F"])
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_result_timeout_preserves_partial_file_and_usage_from_str_or_bytes_output(self):
        for captured in (COMPLETED_TURN_JSONL, COMPLETED_TURN_JSONL.encode("utf-8")):
            with self.subTest(captured_type=type(captured).__name__):
                self.failure = subprocess.TimeoutExpired(
                    cmd=["codex.exe"], timeout=600, output=captured,
                )
                self.write_before_failure = True
                self.answer = "超时前的部分回答"
                # Process cleanup may return the same buffered stream again.
                self.stdout = COMPLETED_TURN_JSONL

                with self.assertRaisesRegex(codex_runner.CodexExecutionError, "600") as raised:
                    self.request_result()

                self.assertEqual(raised.exception.details.text, self.answer)
                self.assertEqual(raised.exception.details.usage, {
                    "input_tokens": 184, "output_tokens": 37, "reasoning_tokens": 12,
                })
                self.assertTrue(self.processes[-1].killed)
                self.assertTrue(self.processes[-1].reaped)
                self.assert_output_removed()

    def test_result_timeout_uses_last_usage_from_exception_and_recovery_without_duplication(self):
        first = '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}\n'
        recovered = first + (
            '{"type":"turn.completed","usage":{"input_tokens":20,"output_tokens":7}}\n'
        )
        self.failure = subprocess.TimeoutExpired(
            cmd=["codex.exe"], timeout=600, output=first.encode("utf-8"),
        )
        self.stdout = recovered

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()

        self.assertEqual(raised.exception.details.usage, {
            "input_tokens": 20, "output_tokens": 7, "reasoning_tokens": None,
        })
        self.assert_output_removed()

    def test_result_communication_failure_preserves_partial_file_and_recovered_usage(self):
        self.failure = OSError("original communication failure")
        self.write_before_failure = True
        self.answer = "通信失败前的部分回答"
        self.stdout = COMPLETED_TURN_JSONL

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "通信失败") as raised:
            self.request_result()

        self.assertEqual(raised.exception.details.text, self.answer)
        self.assertEqual(raised.exception.details.usage, {
            "input_tokens": 184, "output_tokens": 37, "reasoning_tokens": 12,
        })
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_result_timeout_without_partial_data_keeps_empty_details(self):
        self.failure = subprocess.TimeoutExpired(cmd=["codex.exe"], timeout=600)

        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()

        self.assertIsNone(raised.exception.details.text)
        self.assertIsNone(raised.exception.details.usage)
        self.assertTrue(self.processes[0].killed)
        self.assertTrue(self.processes[0].reaped)
        self.assert_output_removed()

    def test_legacy_timeout_still_raises_compatible_execution_error_with_original_message(self):
        self.failure = subprocess.TimeoutExpired(
            cmd=["codex.exe"], timeout=120, output=COMPLETED_TURN_JSONL,
        )
        self.write_before_failure = True
        self.answer = "旧接口部分回答"

        with self.assertRaisesRegex(codex_runner.CodexExecutionError, "超过 120 秒，已终止"):
            self.request()

        self.assert_output_removed()

    def test_result_keeps_safe_arguments_config_modes_and_custom_timeout(self):
        for use_user_config in (False, True):
            with self.subTest(use_user_config=use_user_config):
                self.request_result(timeout=47, use_user_config=use_user_config)
                process = self.processes[-1]
                expected = [str(self.codex.resolve()), "exec", "--json"]
                if not use_user_config:
                    expected.append("--ignore-user-config")
                expected.extend([
                    "--model", "gpt-6-astra", "-c", 'model_reasoning_effort="low"',
                    "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
                    "--output-last-message", str(process.output_path), "-",
                ])
                self.assertEqual(process.args, expected)
                self.assertIs(process.kwargs["shell"], False)
                self.assertEqual(process.communications, [("challenge", 47)])
                self.assert_output_removed()

    def test_result_preserves_path_and_login_validation_before_exec(self):
        request = getattr(codex_runner, "request_codex_completion_result", None)
        self.assertTrue(callable(request), "structured Codex completion entry point is missing")
        with self.assertRaises(codex_runner.CodexUnavailableError):
            request(str(self.root / "missing/codex.exe"), "gpt-6-astra", "low", "challenge")
        self.login_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="Bearer secret", stderr="token=secret"
        )
        with self.assertRaises(codex_runner.CodexAuthenticationError) as raised:
            self.request_result()
        self.assertNotIn("secret", str(raised.exception))
        self.popen.assert_not_called()

    def test_result_sanitizes_structured_errors_and_cleans_output(self):
        self.returncode = 1
        self.stdout = '''\
{"type":"thread.started","thread_id":"019abcde-1234-7000-8000-123456789abc"}
{"type":"turn.started"}
{"type":"error","message":"failed api_key=secret-key Bearer secret-bearer"}
{"type":"turn.failed","error":{"message":"failed token=secret-token sk-secretvalue"}}
'''
        self.stderr = "startup warning secret"
        with self.assertRaises(codex_runner.CodexExecutionError) as raised:
            self.request_result()
        self.assertIn("failed", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("startup", str(raised.exception))
        self.assert_output_removed()

    def test_legacy_default_timeout_and_text_return_are_preserved_with_jsonl_usage(self):
        self.stdout = COMPLETED_TURN_JSONL

        result = codex_runner.request_codex_completion(
            str(self.codex), "gpt-6-astra", "low", "legacy challenge"
        )
        self.assertEqual(result, "1, 2, 3")
        self.assertEqual(self.processes[0].communications, [("legacy challenge", 120)])
        self.assert_output_removed()


if __name__ == "__main__":
    unittest.main()
