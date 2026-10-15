import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from magi import providers


SCHEMA = {
    "type": "object",
    "properties": {"vote": {"type": "string"}},
    "required": ["vote"],
    "additionalProperties": False,
}
DECISION = {"vote": "approve"}


class SubscriptionGuardTests(unittest.TestCase):
    def test_codex_has_no_command_execution_or_external_tools(self):
        args = providers._command("codex", ["codex.exe"], SCHEMA, Path("work"), None)
        for setting in ("features.shell_tool=false", "features.multi_agent=false", "agents.enabled=false", "features.hooks=false", "features.apps=false", "features.plugins=false", 'web_search="disabled"', "project_doc_max_bytes=0"):
            self.assertIn(setting, args)

    def test_grok_denies_even_implicitly_available_tools(self):
        args = providers._command("grok", ["grok.exe"], SCHEMA, Path("work"), None)
        self.assertEqual(args[args.index("--deny") + 1], "*")

    def test_missing_cli_never_starts_a_process(self):
        with patch.object(providers, "_executable", return_value=None), patch.object(providers, "_run_process") as run:
            result = providers.preflight("codex")
        self.assertFalse(result["available"])
        self.assertFalse(result["subscription_ready"])
        run.assert_not_called()

    def test_codex_requires_chatgpt_login(self):
        for text, accepted in [
            ("Logged in using ChatGPT\n", True),
            ("Logged in using an API key\n", False),
            ("Not logged in\n", False),
        ]:
            with self.subTest(text=text), patch.object(providers, "_executable", return_value=["codex.exe"]), patch.object(
                providers, "_run_process", return_value=providers._ProcessResult(0, stderr=text)
            ):
                result = providers.preflight("codex")
            self.assertEqual(result["subscription_ready"], accepted)

    def test_claude_requires_logged_in_first_party_subscription(self):
        cases = [
            ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}, True),
            ({"loggedIn": True, "authMethod": "claudeai", "apiProvider": "firstParty"}, True),
            ({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}, False),
            ({"loggedIn": True, "authMethod": "claudeai", "apiProvider": "bedrock"}, False),
            ({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}, False),
            ({"loggedIn": True}, False),
        ]
        for payload, accepted in cases:
            with self.subTest(payload=payload), patch.object(providers, "_executable", return_value=["claude.exe"]), patch.object(
                providers, "_run_process", return_value=providers._ProcessResult(0, json.dumps(payload))
            ):
                self.assertEqual(providers.preflight("claude")["subscription_ready"], accepted)

    def test_api_auth_failure_stops_before_inference(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_executable", return_value=["codex.exe"]), patch.object(
            providers, "_run_process", return_value=providers._ProcessResult(0, stderr="Logged in using an API key")
        ) as run:
            result = providers.invoke("codex", "Judge this.", SCHEMA, Path(temporary) / "codex")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(result["status"], "error")
            self.assertIsNone(result["decision"])

    def test_environment_removes_api_and_provider_overrides(self):
        host = {
            "PATH": "bin", "USERPROFILE": "profile", "CODEX_HOME": "subscription-home",
            "OPENAI_API_KEY": "fake", "ANTHROPIC_API_KEY": "fake",
            "ANTHROPIC_BASE_URL": "endpoint", "CLAUDE_CODE_USE_BEDROCK": "1",
            "GROK_API_KEY": "fake", "XAI_API_KEY": "fake", "AZURE_OPENAI_ENDPOINT": "endpoint",
            "AWS_PROFILE": "billing", "GOOGLE_APPLICATION_CREDENTIALS": "path",
            "CODEX_MODEL_PROVIDER": "custom", "api_key": "fake", "OPENROUTER_API_KEY": "fake",
        }
        with patch.dict(os.environ, host, clear=True):
            env = providers._child_environment()
        self.assertEqual(env, {"PATH": "bin", "USERPROFILE": "profile", "CODEX_HOME": "subscription-home"})
        self.assertEqual(host["OPENAI_API_KEY"], "fake")

    def test_grok_requires_api_auth_disabled_and_an_isolated_oauth_login(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "grok"
            home.mkdir()
            # The guard only checks existence; an opaque file is never read.
            (home / "auth.json").write_bytes(b"\xffopaque-credential-file")
            payload = {
                "loginPolicy": {"apiKeyAuthDisabled": True},
                "configSources": {"layers": [
                    {"role": "requirements", "path": str(home / "requirements.toml")},
                    {"role": "user", "path": str(home / "config.toml")},
                ]},
                "hooks": [], "plugins": [], "mcpServers": [],
            }
            with patch.object(providers, "grok_home", return_value=home), patch.object(
                providers, "_executable", return_value=["grok.exe"]
            ), patch.object(providers, "_run_process", return_value=providers._ProcessResult(0, json.dumps(payload))):
                result = providers.preflight("grok")
            self.assertTrue(result["subscription_ready"])
            self.assertIn("not checked", result["warning"])

            for key, value in [
                ("loginPolicy", {"apiKeyAuthDisabled": False}),
                ("configSources", {"layers": [{"path": str(home / "unknown.toml")}]}),
                ("hooks", [{"event": "stop"}]),
                ("plugins", [{"name": "unexpected"}]),
            ]:
                rejected = {**payload, key: value}
                with self.subTest(key=key), patch.object(providers, "grok_home", return_value=home), patch.object(
                    providers, "_executable", return_value=["grok.exe"]
                ), patch.object(providers, "_run_process", return_value=providers._ProcessResult(0, json.dumps(rejected))):
                    self.assertFalse(providers.preflight("grok")["subscription_ready"])

    def test_grok_environment_isolates_external_user_configuration(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "grok_home", return_value=Path(temporary) / "grok"):
            env = providers._provider_environment("grok")
            self.assertEqual(env["HOME"], env["USERPROFILE"])
            self.assertEqual(env["GROK_DISABLE_AUTOUPDATER"], "1")
            self.assertEqual(env["GROK_DISABLE_API_KEY_AUTH"], "1")
            self.assertEqual(env["GROK_CLAUDE_HOOKS_ENABLED"], "0")
            self.assertIn("[auth]\ndisable_api_key_auth = true", (Path(env["GROK_HOME"]) / "config.toml").read_text())
            self.assertFalse((Path(env["GROK_HOME"]) / "requirements.toml").exists())

    def test_grok_does_not_overwrite_the_deployment_requirements_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "grok"
            home.mkdir()
            cache = home / "requirements.toml"
            cache.write_bytes(b"existing-deployment-cache")
            with patch.object(providers, "grok_home", return_value=home):
                providers._provider_environment("grok")
            self.assertEqual(cache.read_bytes(), b"existing-deployment-cache")


class OutputTests(unittest.TestCase):
    def test_codex_uses_final_file_instead_of_log_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "final.json").write_text(json.dumps(DECISION), encoding="utf-8")
            self.assertEqual(providers._parse_decision("codex", "unrelated logs", path), DECISION)

    def test_claude_uses_schema_payload(self):
        payload = {"type": "result", "result": "ignored", "structured_output": DECISION, "is_error": False}
        self.assertEqual(providers._parse_decision("claude", json.dumps(payload), Path(".")), DECISION)

    def test_error_and_unstructured_responses_are_rejected(self):
        for payload in [
            {"is_error": True, "structured_output": DECISION},
            {"result": json.dumps(DECISION)},
            {"structured_output": [DECISION]},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                providers._parse_decision("claude", json.dumps(payload), Path("."))

    def test_malformed_json_does_not_turn_into_a_vote(self):
        with self.assertRaises(ValueError):
            providers._parse_decision("claude", "An error occurred", Path("."))

    def test_grok_extracts_judgement_from_documented_text_envelope(self):
        payload = {"text": json.dumps(DECISION), "stopReason": "end_turn", "sessionId": "opaque"}
        self.assertEqual(providers._parse_decision("grok", json.dumps(payload), Path(".")), DECISION)

    def test_grok_supports_schema_result_field_variants(self):
        for key in ("structured_output", "structuredOutput"):
            with self.subTest(key=key):
                self.assertEqual(providers._parse_decision("grok", json.dumps({key: DECISION}), Path(".")), DECISION)

    def test_grok_error_and_metadata_cannot_become_a_judgement(self):
        cases = [
            {"text": "API unavailable", "error": "failed"},
            {"text": json.dumps(DECISION), "stopReason": "max_tokens"},
            {"sessionId": "opaque", "num_turns": 2},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                providers._parse_decision("grok", json.dumps(payload), Path("."))


class InvocationTests(unittest.TestCase):
    def test_success_preserves_logs_and_passes_prompt_by_stdin(self):
        calls = []

        def fake_run(command, *, cwd, env, timeout, input_text=""):
            calls.append((command, input_text, env))
            if command[-2:] == ["login", "status"]:
                return providers._ProcessResult(0, stderr="Logged in using ChatGPT")
            (cwd / "final.json").write_text(json.dumps(DECISION), encoding="utf-8")
            return providers._ProcessResult(0, "raw stdout\n", "raw stderr\n")

        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_executable", return_value=["codex.exe"]), patch.object(
            providers, "_run_process", side_effect=fake_run
        ):
            directory = Path(temporary) / "run"
            result = providers.invoke("codex", "日本語の作品を審査", SCHEMA, directory, model="chosen-model")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["decision"], DECISION)
            self.assertEqual(result["model_requested"], "chosen-model")
            self.assertEqual((directory / "stdout.txt").read_text(encoding="utf-8"), "raw stdout\n")
            self.assertEqual((directory / "stderr.txt").read_text(encoding="utf-8"), "raw stderr\n")
            command, input_text, _ = calls[1]
            self.assertEqual(input_text, "日本語の作品を審査")
            self.assertEqual(command[-1], "-")
            self.assertIn('forced_login_method="chatgpt"', command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("chosen-model", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_claude_empty_tools_survives_as_a_separate_argument(self):
        command = providers._command("claude", ["claude.exe"], SCHEMA, Path("run"), None)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--safe-mode", command)
        self.assertNotIn("--bare", command)

    def test_grok_uses_cli_default_or_explicit_grok_model(self):
        command = providers._command("grok", ["grok.exe"], SCHEMA, Path("run"), None)
        self.assertNotIn("--model", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        explicit = providers._command("grok", ["grok.exe"], SCHEMA, Path("run"), "grok-4.7")
        self.assertEqual(explicit[explicit.index("--model") + 1], "grok-4.7")
        with patch.object(providers, "_run_process") as run:
            result = providers.invoke("grok", "prompt", SCHEMA, Path("unused"), model="custom-billed-model")
        self.assertEqual(result["status"], "error")
        run.assert_not_called()

    def test_explicit_grok_model_still_requires_subscription_policy(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_executable", return_value=["grok.exe"]), patch.object(
            providers, "_subscription_error", return_value="API authentication is not disabled"
        ), patch.object(providers, "_run_process") as run:
            result = providers.invoke("grok", "prompt", SCHEMA, Path(temporary) / "run", model="grok-4.7")
        self.assertEqual(result["status"], "error")
        run.assert_not_called()

    def test_grok_passes_prompt_only_through_its_file(self):
        calls = []
        def fake_run(command, *, cwd, env, timeout, input_text=""):
            calls.append(input_text)
            self.assertEqual((cwd / "prompt.txt").read_text(encoding="utf-8"), "source data")
            return providers._ProcessResult(0, json.dumps({"text": json.dumps(DECISION), "stopReason": "end_turn"}))
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_executable", return_value=["grok.exe"]), patch.object(
            providers, "_subscription_error", return_value=None
        ), patch.object(providers, "_run_process", side_effect=fake_run):
            result = providers.invoke("grok", "source data", SCHEMA, Path(temporary) / "run")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, [None])

    def test_nonempty_work_directory_is_rejected_without_calling_cli(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_run_process") as run:
            directory = Path(temporary)
            (directory / "existing.txt").write_text("keep", encoding="utf-8")
            result = providers.invoke("codex", "prompt", SCHEMA, directory)
            self.assertEqual(result["status"], "error")
            self.assertEqual((directory / "existing.txt").read_text(), "keep")
            run.assert_not_called()

    def test_timeout_does_not_become_a_success(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(providers, "_executable", return_value=["claude.exe"]), patch.object(
            providers, "_subscription_error", return_value=None
        ), patch.object(providers, "_run_process", return_value=providers._ProcessResult(-1, "partial", "", True)):
            result = providers.invoke("claude", "prompt", SCHEMA, Path(temporary) / "run", timeout=2)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["decision"])
        self.assertIn("timed out", result["error"])

    def test_unknown_provider_is_a_reportable_error(self):
        result = providers.invoke("unknown", "prompt", SCHEMA, Path("unused"))
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["decision"])


class ProcessTests(unittest.TestCase):
    def test_devnull_stdin_for_file_prompt_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = providers._run_process(
                [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
                cwd=Path(temporary), env=providers._child_environment(), timeout=5, input_text=None,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "''")

    def test_utf8_stdin_and_stdout_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = providers._run_process(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                cwd=Path(temporary), env=providers._child_environment(), timeout=5,
                input_text="MAGI 審査 合議",
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "MAGI 審査 合議")

    def test_timeout_terminates_a_running_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = providers._run_process(
                [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
                cwd=Path(temporary), env=providers._child_environment(), timeout=1,
            )
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("started", result.stdout)


if __name__ == "__main__":
    unittest.main()


class ModelDetectionTests(unittest.TestCase):
    def test_reads_the_model_each_cli_reports(self):
        claude = json.dumps({"modelUsage": {"claude-haiku-4-5-20251001": {"outputTokens": 12}, "claude-opus-5-5[1m]": {"outputTokens": 900}}})
        self.assertEqual(providers.detected_model("claude", claude, ""), "claude-opus-5-5")
        grok = json.dumps({"modelUsage": {"grok-4.7": {"outputTokens": 80}}})
        self.assertEqual(providers.detected_model("grok", grok, ""), "grok-4.7")
        header = "OpenAI Codex v0.162\n--------\nworkdir: x\nmodel: gpt-6.1-sol\nprovider: openai\n"
        self.assertEqual(providers.detected_model("codex", "{}", header), "gpt-6.1-sol")

    def test_missing_model_information_is_unknown_not_guessed(self):
        self.assertIsNone(providers.detected_model("claude", "not json", ""))
        self.assertIsNone(providers.detected_model("grok", json.dumps({"text": "{}"}), ""))
        self.assertIsNone(providers.detected_model("codex", "", "no header"))
