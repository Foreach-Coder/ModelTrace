"""Discover and run the Windows Codex CLI with fixed, isolated arguments."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from completion_errors import CompletionFailureDetails, StructuredCompletionError


@dataclass(frozen=True)
class CodexRuntime:
    path: str
    source: str
    version: str


class CodexUnavailableError(RuntimeError):
    """No usable Windows Codex executable could be resolved."""


class CodexAuthenticationError(RuntimeError):
    """Codex has no usable existing login."""


class CodexExecutionError(StructuredCompletionError):
    """An isolated Codex request failed."""


def _is_windows() -> bool:
    return sys.platform == "win32"


def _version_key(version: str) -> tuple[object, ...]:
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
        version,
    )
    if match is None:
        return (0, 0, 0, -1, ())
    prerelease = match.group(4)
    identifiers: list[tuple[int, object]] = []
    if prerelease is not None:
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    return (0, 0, 0, -1, ())
                identifiers.append((0, int(identifier)))
            else:
                identifiers.append((1, identifier))
    stable = 1 if prerelease is None else 0
    return (
        int(match.group(1)), int(match.group(2)), int(match.group(3)),
        stable, tuple(identifiers),
    )


def _inspect_candidate(path: str | Path, source: str) -> CodexRuntime | None:
    try:
        executable = Path(path).resolve()
        if executable.name.lower() != "codex.exe" or not executable.is_file():
            return None
        result = subprocess.run(
            [str(executable), "--version"], shell=False, capture_output=True,
            text=True, encoding="utf-8", timeout=5,
        )
        match = re.fullmatch(r"codex-cli\s+(\S+)", result.stdout.strip())
        if result.returncode != 0 or match is None:
            return None
        return CodexRuntime(str(executable), source, match.group(1))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def discover_codex(explicit_path: str = "") -> CodexRuntime:
    """Resolve a validated runtime; a supplied manual path never falls back."""
    if not _is_windows():
        raise CodexUnavailableError("Codex 自动测试仅支持 Windows")
    if explicit_path:
        runtime = _inspect_candidate(explicit_path, "manual")
        if runtime is None:
            raise CodexUnavailableError(f"Codex 路径无效或版本检查失败：{explicit_path}")
        return runtime

    environment_path = os.environ.get("MODELTRACE_CODEX_PATH", "")
    if environment_path:
        runtime = _inspect_candidate(environment_path, "environment")
        if runtime is not None:
            return runtime

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        root = Path(local_appdata)
        candidates = []
        for path in (root / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"):
            runtime = _inspect_candidate(path, "desktop")
            if runtime is not None:
                try:
                    candidates.append((runtime, path.stat().st_mtime))
                except OSError:
                    continue
        if candidates:
            return max(candidates, key=lambda item: (_version_key(item[0].version), item[1]))[0]
        runtime = _inspect_candidate(
            root / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe", "install"
        )
        if runtime is not None:
            return runtime

    path_candidate = shutil.which("codex.exe")
    if path_candidate:
        runtime = _inspect_candidate(path_candidate, "path")
        if runtime is not None:
            return runtime
    raise CodexUnavailableError("未找到 codex.exe")


def _check_login(runtime: CodexRuntime) -> None:
    try:
        result = subprocess.run(
            [runtime.path, "login", "status"], shell=False, capture_output=True,
            text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise CodexAuthenticationError("无法检查 Codex 登录状态，请在桌面版或 CLI 中确认登录") from error
    if result.returncode != 0:
        raise CodexAuthenticationError("Codex 未登录，请先在桌面版或 CLI 中完成登录")


def get_codex_status(explicit_path: str = "") -> dict[str, object]:
    """Return runtime and login status without exposing authentication output."""
    status: dict[str, object] = {
        "available": False, "authenticated": False,
        "path": "", "source": "", "version": "",
    }
    try:
        runtime = discover_codex(explicit_path)
    except CodexUnavailableError as error:
        status["error"] = str(error)
        return status
    status.update(available=True, path=runtime.path, source=runtime.source, version=runtime.version)
    try:
        _check_login(runtime)
    except CodexAuthenticationError as error:
        status["error"] = str(error)
        return status
    status["authenticated"] = True
    return status


def list_codex_models(
    explicit_path: str = "", use_user_config: bool = False,
) -> list[dict[str, str]]:
    """Return picker-visible models from Codex without limiting manual input."""
    runtime = discover_codex(explicit_path)
    args = [runtime.path, "debug", "models"]
    if not use_user_config:
        args.append("--bundled")
    try:
        result = subprocess.run(
            args, shell=False, capture_output=True, text=True,
            encoding="utf-8", timeout=20,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise CodexExecutionError("无法读取 Codex 模型目录") from error
    if result.returncode != 0:
        diagnostic = _sanitized_diagnostic(result.stderr or result.stdout)
        raise CodexExecutionError(
            "Codex 模型目录请求失败" + (f"：{diagnostic}" if diagnostic else "")
        )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise CodexExecutionError("Codex 模型目录格式无效") from error
    entries = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise CodexExecutionError("Codex 模型目录格式无效")

    models = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("visibility", "list") != "list":
            continue
        model_id = entry.get("slug") or entry.get("model") or entry.get("id")
        if (
            not isinstance(model_id, str)
            or re.fullmatch(r"[A-Za-z0-9._/:-]{1,128}", model_id) is None
            or model_id in seen
        ):
            continue
        label = entry.get("display_name") or entry.get("displayName") or model_id
        if not isinstance(label, str) or not label.strip():
            label = model_id
        seen.add(model_id)
        models.append({"id": model_id, "label": label.strip()})
    return models


def _sanitized_diagnostic(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [已隐藏]", text)
    text = re.sub(
        r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
        r"\1[已隐藏]", text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[已隐藏]", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())[-1000:]


def _unwrap_error_message(value: object) -> str:
    json_layers = 0
    while True:
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict) and "message" in error:
                value = error["message"]
                continue
            if "message" in value:
                value = value["message"]
                continue
            return ""
        if not isinstance(value, str):
            return ""
        value = value.strip()
        if not value or json_layers == 2:
            return value
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
        if not isinstance(decoded, (str, dict)):
            return value
        value = decoded
        json_layers += 1


def _structured_error(stdout: str) -> str:
    diagnostic = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error":
            value = event.get("message")
        elif event.get("type") == "turn.failed":
            value = event.get("error")
        else:
            continue
        message = _unwrap_error_message(value)
        if message:
            diagnostic = message
    return diagnostic


def _terminate_process_tree(process: subprocess.Popen) -> object:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(int(process.pid)), "/T", "/F"],
            shell=False, capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        recovered = process.communicate(timeout=5)
        if isinstance(recovered, tuple) and recovered:
            return recovered[0]
    except (OSError, UnicodeError, subprocess.SubprocessError):
        pass
    return None


def _captured_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return ""


def _merge_captured_stdout(initial: object, recovered: object) -> str:
    """Combine timeout and reap output without duplicating a repeated buffer."""
    before = _captured_text(initial)
    after = _captured_text(recovered)
    if not before:
        return after
    if not after:
        return before
    if after.startswith(before):
        return after
    if before.startswith(after):
        return before
    separator = "" if before.endswith("\n") or after.startswith("\n") else "\n"
    return before + separator + after


def _completed_turn_usage(stdout: str) -> dict[str, int | None]:
    """Read the last reported usage mapping without inferring missing counts."""
    usage: dict[str, int | None] = {
        "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        reported = event.get("usage")
        if not isinstance(reported, dict) or not any(key in reported for key in usage):
            continue
        parsed = {
            key: value if type(value := reported.get(key)) is int and value >= 0 else None
            for key in usage
        }
        if any(value is not None for value in parsed.values()):
            usage = parsed
    return usage


def _available_usage(usage: dict[str, int | None]) -> dict[str, int | None] | None:
    return usage if any(value is not None for value in usage.values()) else None


def _failure_details(output_path: Path, stdout: str) -> CompletionFailureDetails:
    """Best-effort partial data collection that never masks the original failure."""
    answer = None
    try:
        if output_path.exists():
            answer = output_path.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        pass
    try:
        usage = _available_usage(_completed_turn_usage(stdout))
    except (TypeError, ValueError):
        usage = None
    return CompletionFailureDetails(text=answer, usage=usage)


def _execute_codex_completion(
    codex_path: str, model: str, reasoning_effort: str, prompt: str,
    timeout: int, use_user_config: bool,
) -> tuple[str, str]:
    """Execute one authenticated, ephemeral, read-only Codex challenge."""
    if not isinstance(model, str) or re.fullmatch(r"[A-Za-z0-9._/:-]{1,128}", model) is None:
        raise ValueError("model 必须是有效的模型标识，最多 128 个字符")
    if not isinstance(reasoning_effort, str) or reasoning_effort not in ("low", "medium", "high", "xhigh"):
        raise ValueError("reasoning_effort 仅支持 low、medium、high、xhigh")
    runtime = discover_codex(codex_path)
    _check_login(runtime)

    output_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="modeltrace-codex-", suffix=".txt", delete=False) as output:
            output_path = Path(output.name)
        args = [runtime.path, "exec", "--json"]
        if not use_user_config:
            args.append("--ignore-user-config")
        args.extend([
            "--model", model,
            "-c", f'model_reasoning_effort="{reasoning_effort}"',
            "--ephemeral",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--output-last-message", str(output_path),
            "-",
        ])
        process = subprocess.Popen(
            args, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            stdout, stderr = process.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            recovered_stdout = _terminate_process_tree(process)
            captured_stdout = _merge_captured_stdout(error.output, recovered_stdout)
            raise CodexExecutionError(
                f"Codex 执行超过 {timeout} 秒，已终止",
                details=_failure_details(output_path, captured_stdout),
            ) from error
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            recovered_stdout = _terminate_process_tree(process)
            raise CodexExecutionError(
                "Codex 执行通信失败",
                details=_failure_details(output_path, _captured_text(recovered_stdout)),
            ) from error
        usage = _available_usage(_completed_turn_usage(stdout))
        try:
            answer = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        except (OSError, UnicodeError) as error:
            raise CodexExecutionError(
                "Codex 启动失败或无法读取回答",
                details=CompletionFailureDetails(usage=usage),
            ) from error
        if process.returncode != 0:
            raw_diagnostic = _structured_error(stdout) or stderr
            diagnostic = _sanitized_diagnostic(raw_diagnostic)
            raise CodexExecutionError(
                "Codex 执行失败" + (f"：{diagnostic}" if diagnostic else ""),
                details=CompletionFailureDetails(text=answer or None, usage=usage),
            )
        if not answer:
            raise CodexExecutionError(
                "Codex 未返回有效回答",
                details=CompletionFailureDetails(usage=usage),
            )
        return answer, stdout
    except (OSError, UnicodeError) as error:
        raise CodexExecutionError("Codex 启动失败或无法读取回答") from error
    finally:
        if output_path is not None:
            output_path.unlink(missing_ok=True)


def request_codex_completion_result(
    codex_path: str, model: str, reasoning_effort: str, prompt: str,
    timeout: int = 600, use_user_config: bool = False,
) -> dict[str, object]:
    """Return final text and nullable usage from one isolated Codex request."""
    answer, stdout = _execute_codex_completion(
        codex_path, model, reasoning_effort, prompt, timeout, use_user_config,
    )
    return {"text": answer, "usage": _completed_turn_usage(stdout)}


def request_codex_completion(
    codex_path: str, model: str, reasoning_effort: str, prompt: str,
    timeout: int = 120, use_user_config: bool = False,
) -> str:
    """Preserve the text-only request and its existing 120-second timeout."""
    answer, _ = _execute_codex_completion(
        codex_path, model, reasoning_effort, prompt, timeout, use_user_config,
    )
    return answer
