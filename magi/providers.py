"""Subscription-only adapters for the three vendors' official command lines.

No API credential is read by this module. Authentication is checked using each
CLI's own status interface before inference, and ambiguous states fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any


PROVIDERS = ("codex", "claude", "grok")

# Keep login locations such as HOME, APPDATA and CODEX_HOME. Remove credential
# overrides, alternate endpoints and provider selectors inherited by the host.
_ENV_PREFIXES = (
    "ANTHROPIC_", "CLAUDE_", "OPENAI_", "GROK_", "XAI_", "X_AI_",
    "AZURE_", "AWS_", "GOOGLE_", "GEMINI_", "VERTEX_", "BEDROCK_",
)
_ENV_NAMES = {
    "API_KEY", "API_BASE", "API_BASE_URL", "CODEX_API_KEY",
    "CODEX_API_BASE_URL", "CODEX_MODEL_PROVIDER", "CODEX_PROFILE",
}


@dataclass
class _ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def _child_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items()
        if key.upper() not in _ENV_NAMES
        and not key.upper().startswith(_ENV_PREFIXES)
        and not key.upper().endswith("_API_KEY")
        and (not key.upper().startswith("CODEX_") or key.upper() == "CODEX_HOME")
    }


def grok_home() -> Path:
    """The app's isolated OAuth home, outside source code and exported runs."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return (base / "MagiJudge" / "grok").resolve()


def _provider_environment(provider: str) -> dict[str, str]:
    env = _child_environment()
    if provider == "grok":
        home = grok_home()
        home.mkdir(parents=True, exist_ok=True)
        # This directory belongs exclusively to this app. Reapply public policy
        # without ever opening auth.json or reading cached credential values.
        # requirements.toml is the deployment's signed cache. Native startup
        # may replace or remove it; enforce our local restriction in user config
        # and the documented process environment instead of editing that cache.
        (home / "config.toml").write_text(
            "[auth]\ndisable_api_key_auth = true\n\n"
            "[cli]\nauto_update = false\nuse_leader = false\n\n"
            "[compat.claude]\nskills = false\nrules = false\nagents = false\nmcps = false\nhooks = false\n\n"
            "[compat.cursor]\nskills = false\nrules = false\nagents = false\nmcps = false\nhooks = false\n\n"
            "[compat.codex]\nskills = false\nhooks = false\n", encoding="utf-8",
        )
        isolated_user = home / "host-home"
        isolated_user.mkdir(exist_ok=True)
        env["HOME"] = str(isolated_user)
        env["USERPROFILE"] = str(isolated_user)
        env["GROK_HOME"] = str(home)
        env["GROK_DISABLE_AUTOUPDATER"] = "1"
        env["GROK_DISABLE_API_KEY_AUTH"] = "1"
        for vendor in ("CLAUDE", "CURSOR"):
            for surface in ("SKILLS", "RULES", "AGENTS", "MCPS", "HOOKS"):
                env[f"GROK_{vendor}_{surface}_ENABLED"] = "0"
    return env


def _executable(provider: str) -> list[str] | None:
    """Bypass npm .cmd/.ps1 shims so JSON and empty arguments survive Windows."""
    found = shutil.which(provider)
    if not found:
        return None
    path = Path(found)
    if path.suffix.lower() not in {".cmd", ".bat", ".ps1"}:
        return [str(path)]
    if provider == "claude":
        package = path.parent / "node_modules" / "@anthropic-ai" / "claude-code"
        native = package / "bin" / "claude.exe"
        if native.is_file():
            return [str(native)]
        script = package / "cli.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    elif provider == "codex":
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    # Never invoke a shell just to make an unknown shim work.
    return None


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _run_process(
    command: list[str], *, cwd: Path, env: dict[str, str],
    timeout: int, input_text: str | None = "",
) -> _ProcessResult:
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        options["start_new_session"] = True
    with subprocess.Popen(
        command, cwd=cwd, env=env, shell=False,
        stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **options,
    ) as process:
        try:
            stdout, stderr = process.communicate(None if input_text is None else input_text.encode("utf-8"), timeout=timeout)
            expired = False
        except subprocess.TimeoutExpired as exc:
            _terminate_tree(process)
            expired = True
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = exc.stdout or b"", exc.stderr or b""
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
        return _ProcessResult(
            process.returncode if process.returncode is not None else -1,
            stdout.decode("utf-8-sig", errors="replace"),
            stderr.decode("utf-8-sig", errors="replace"), expired,
        )


def _save_process(work_dir: Path, prefix: str, result: _ProcessResult) -> None:
    (work_dir / f"{prefix}stdout.txt").write_text(result.stdout, encoding="utf-8")
    (work_dir / f"{prefix}stderr.txt").write_text(result.stderr, encoding="utf-8")


def _json_object(text: str) -> dict[str, Any]:
    value = json.loads(text.strip().removeprefix("\ufeff"))
    if not isinstance(value, dict):
        raise ValueError("CLI output must be a JSON object")
    return value


def _subscription_error(
    provider: str, command: list[str], cwd: Path, env: dict[str, str],
    timeout: int, save_logs: bool = False,
) -> str | None:
    if provider == "codex":
        args = ["login", "status"]
    elif provider == "claude":
        args = ["--safe-mode", "auth", "status"]
    else:
        args = ["inspect", "--json"]
    try:
        result = _run_process(command + args, cwd=cwd, env=env, timeout=timeout)
    except OSError:
        return f"{provider} authentication check could not start."
    if save_logs:
        _save_process(cwd, "auth-", result)
    if result.timed_out:
        return f"{provider} authentication check timed out."
    if result.returncode:
        return f"{provider} subscription login is not ready. Run its official login command."
    if provider == "codex":
        if re.search(r"(?im)^\s*Logged in using ChatGPT\s*$", result.stdout + "\n" + result.stderr):
            return None
    elif provider == "claude":
        try:
            auth = _json_object(result.stdout)
        except (ValueError, json.JSONDecodeError):
            return "Claude authentication status could not be verified."
        if (
            auth.get("loggedIn") is True
            and auth.get("authMethod") in {"claude.ai", "claudeai"}
            and auth.get("apiProvider") == "firstParty"
        ):
            return None
    else:
        try:
            inspection = _json_object(result.stdout)
        except (ValueError, json.JSONDecodeError):
            return "Grok subscription-only login policy could not be verified."
        policy = inspection.get("loginPolicy")
        if not isinstance(policy, dict) or policy.get("apiKeyAuthDisabled") is not True:
            return "Grok did not confirm that API key authentication is disabled."
        config_sources = inspection.get("configSources")
        sources = config_sources.get("layers") if isinstance(config_sources, dict) else None
        expected = {grok_home() / "requirements.toml", grok_home() / "config.toml"}
        if not isinstance(sources, list) or any(
            not isinstance(source, dict)
            or not isinstance(source.get("path"), str)
            or Path(source["path"]).resolve() not in expected
            for source in sources
        ):
            return "Grok loaded additional configuration; custom providers and API fallback are disabled."
        if any(inspection.get(key) for key in ("hooks", "plugins", "mcpServers")):
            return "Grok loaded external hooks, plugins, or MCP servers; the isolated subscription adapter refuses to run."
        if not (Path(env["GROK_HOME"]) / "auth.json").is_file():
            return "Grok OAuth login is missing in the dedicated app home. Set GROK_HOME to the doctor path and run grok login --oauth."
        return None
    return f"{provider} is not authenticated with a verified subscription; API fallback is disabled."


def preflight(provider: str, timeout: int = 15) -> dict[str, Any]:
    """Return installation and subscription readiness, never credentials."""
    result: dict[str, Any] = {
        "provider": provider, "available": False, "subscription_ready": False, "error": None,
    }
    if provider not in PROVIDERS:
        result["error"] = "Unknown provider."
        return result
    if timeout <= 0:
        result["error"] = "Timeout must be positive."
        return result
    command = _executable(provider)
    if command is None:
        result["error"] = f"The official {provider} CLI executable was not found."
        return result
    result["available"] = True
    try:
        with tempfile.TemporaryDirectory(prefix="magi-auth-") as temporary:
            result["error"] = _subscription_error(
                provider, command, Path(temporary), _provider_environment(provider), timeout,
            )
    except OSError:
        result["error"] = "Subscription readiness check could not access its dedicated working directory."
    result["subscription_ready"] = result["error"] is None
    if provider == "grok":
        result["warning"] = "OAuth token validity is not checked by doctor; the Grok CLI validates it when a request runs."
    return result


def cli_version(provider: str, timeout: int = 15) -> str | None:
    """The CLI's self-reported version, for the run record. Never fatal."""
    command = _executable(provider) if provider in PROVIDERS else None
    if command is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="magi-version-") as temporary:
            result = _run_process(command + ["--version"], cwd=Path(temporary), env=_provider_environment(provider), timeout=timeout)
    except OSError:
        return None
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0][:120] if not result.returncode and not result.timed_out and lines else None


def _command(
    provider: str, executable: list[str], schema: dict[str, Any],
    work_dir: Path, model: str | None,
) -> list[str]:
    schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    if provider == "codex":
        args = [
            "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--ephemeral", "--sandbox", "read-only", "--color", "never",
            "-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"',
            "-c", "features.shell_tool=false", "-c", "features.multi_agent=false",
            "-c", "agents.enabled=false", "-c", "features.hooks=false",
            "-c", "features.apps=false", "-c", "features.plugins=false",
            "-c", 'web_search="disabled"', "-c", "tools.view_image=false",
            "-c", "project_doc_max_bytes=0",
            "--output-schema", str(work_dir / "schema.json"),
            "-o", str(work_dir / "final.json"),
        ]
    elif provider == "claude":
        args = [
            "--safe-mode", "-p", "--tools", "", "--no-session-persistence",
            "--output-format", "json", "--json-schema", schema_json,
        ]
    else:
        args = [
            "--prompt-file", str(work_dir / "prompt.txt"), "--json-schema", schema_json,
            "--tools", "", "--disable-web-search", "--permission-mode", "dontAsk",
            "--deny", "*",
            "--no-subagents", "--max-turns", "2",
        ]
    if model:
        args += ["--model", model]
    if provider == "codex":
        args.append("-")
    return executable + args


def _parse_decision(provider: str, stdout: str, work_dir: Path) -> dict[str, Any]:
    if provider == "codex":
        final = work_dir / "final.json"
        if not final.is_file():
            raise ValueError("Codex did not write final.json")
        return _json_object(final.read_text(encoding="utf-8-sig"))
    payload = _json_object(stdout)
    if payload.get("is_error") is True:
        raise ValueError(f"{provider} reported an unsuccessful result")
    if provider == "claude":
        decision = payload.get("structured_output")
        if not isinstance(decision, dict):
            raise ValueError("Claude did not return structured_output")
        return decision
    # Grok's JSON mode carries response text in `text`; its Messages-compatible
    # result format carries `structured_output`. Accept the camelCase variant
    # used by some JSON-mode releases, but never mistake metadata for a vote.
    if payload.get("error") or payload.get("errors"):
        raise ValueError("Grok reported an unsuccessful result")
    stop_reason = payload.get("stopReason", payload.get("stop_reason"))
    if stop_reason is not None and stop_reason not in {"end_turn", "stop_sequence"}:
        raise ValueError("Grok did not finish the judgement successfully")
    for key in ("structured_output", "structuredOutput"):
        decision = payload.get(key)
        if isinstance(decision, dict):
            return decision
    if isinstance(payload.get("text"), str):
        return _json_object(payload["text"])
    raise ValueError("Grok did not return a structured JSON judgement")


def detected_model(provider: str, stdout: str, stderr: str) -> str | None:
    """The model the CLI reports it actually ran, or None when it does not say."""
    if provider == "codex":
        found = re.search(r"(?m)^model:\s*(\S+)\s*$", f"{stderr}\n{stdout}")
        return found.group(1) if found else None
    try:
        usage = _json_object(stdout).get("modelUsage")
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(usage, dict) or not usage:
        return None
    # Helper models (e.g. a small model for titles) also appear; the judge is
    # the one that wrote the most output.
    def output(item: tuple[str, Any]) -> float:
        value = item[1].get("outputTokens", 0) if isinstance(item[1], dict) else 0
        return value if isinstance(value, (int, float)) else 0
    name = max(usage.items(), key=output)[0]
    return re.sub(r"\[[^\]]*\]$", "", name) or None


def invoke(
    provider: str, prompt: str, schema: dict, work_dir: Path,
    timeout: int = 180, model: str | None = None,
) -> dict:
    """Run one independent judgement in a fresh directory with no API fallback."""
    started = time.monotonic()
    response: dict[str, Any] = {
        "provider": provider, "status": "error", "decision": None, "error": None,
        "duration_seconds": 0.0, "model_requested": model, "model_used": None,
    }
    try:
        if provider not in PROVIDERS:
            raise ValueError("Unknown provider")
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        if provider == "grok" and model is not None and not re.fullmatch(r"grok-[A-Za-z0-9][A-Za-z0-9._-]*", model):
            raise ValueError("Choose a Grok model ID advertised by the official subscription CLI")
        work_dir = Path(work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        if any(work_dir.iterdir()):
            raise ValueError("Provider work directory must be empty")
        (work_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (work_dir / "schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        command = _executable(provider)
        if command is None:
            raise ValueError(f"The official {provider} CLI executable was not found")
        environment = _provider_environment(provider)
        auth_error = _subscription_error(
            provider, command, work_dir, environment, min(timeout, 15), save_logs=True,
        )
        if auth_error:
            raise ValueError(auth_error)
        result = _run_process(
            _command(provider, command, schema, work_dir, model), cwd=work_dir,
            env=environment, timeout=timeout, input_text=None if provider == "grok" else prompt,
        )
        _save_process(work_dir, "", result)
        if result.timed_out:
            raise ValueError(f"{provider} judgement timed out after {timeout} seconds")
        if result.returncode:
            raise ValueError(f"{provider} exited with code {result.returncode}; inspect its local logs")
        response["decision"] = _parse_decision(provider, result.stdout, work_dir)
        response["model_used"] = detected_model(provider, result.stdout, result.stderr)
        response["status"] = "ok"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Do not reflect CLI output or environment values into the report.
        response["error"] = str(exc) if isinstance(exc, ValueError) else "Provider file or process operation failed."
    finally:
        response["duration_seconds"] = round(time.monotonic() - started, 3)
    return response
