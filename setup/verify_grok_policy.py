"""Check that native model discovery cannot remove the app's API-auth restriction."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from magi.providers import _executable, _provider_environment, _run_process


def main():
    command = _executable("grok")
    if command is None:
        raise RuntimeError("Grok CLI not found")
    environment = _provider_environment("grok")
    checks = []
    with tempfile.TemporaryDirectory(prefix="magi-grok-policy-") as temporary:
        for stage in ("before_models", "after_models"):
            if stage == "after_models":
                models = _run_process(command + ["models"], cwd=Path(temporary), env=environment, timeout=30, input_text=None)
                if models.returncode or models.timed_out:
                    raise RuntimeError("Model discovery did not complete")
            output = _run_process(command + ["inspect", "--json"], cwd=Path(temporary), env=environment, timeout=15, input_text=None)
            if output.returncode or output.timed_out:
                raise RuntimeError("Policy inspection did not complete")
            enabled = json.loads(output.stdout)["loginPolicy"]["apiKeyAuthDisabled"] is True
            checks.append({"stage": stage, "api_key_auth_disabled": enabled})
    print(json.dumps(checks))
    if not all(check["api_key_auth_disabled"] for check in checks):
        raise RuntimeError("API-auth restriction did not survive model discovery")


if __name__ == "__main__":
    main()
