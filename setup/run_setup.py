"""Delegate connection setup to the actual vendor CLI, using subscription auth."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from magi.providers import _executable, _provider_environment, _run_process, preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="各社の公式CLIへ、自分の接続セットアップを依頼します")
    parser.add_argument("provider", choices=("claude", "grok"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--model", help="公式CLIが利用可能と表示したモデルID。省略時はCLIの既定値")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 1200:
        parser.error("timeout must be between 30 and 1200 seconds")
    check = preflight(args.provider)
    if not check["subscription_ready"]:
        print(json.dumps(check, ensure_ascii=False))
        return 2
    task = (ROOT / "setup" / "tasks" / f"{args.provider}.txt").read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_dir = ROOT / "setup" / "logs" / f"{args.provider}-{stamp}"
    log_dir.mkdir(parents=True)
    (ROOT / "setup" / "results" / args.provider).mkdir(parents=True, exist_ok=True)
    executable = _executable(args.provider)
    if executable is None:
        raise RuntimeError("Official CLI executable not found")
    if args.provider == "claude":
        command = executable + [
            "--safe-mode", "-p", "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash(python *),Bash(claude *),Bash(grok *)",
            "--output-format", "json", "--no-session-persistence", "--no-chrome",
        ]
        stdin = task
    else:
        task_path = log_dir / "task.txt"
        task_path.write_text(task, encoding="utf-8")
        command = executable + [
            "--prompt-file", str(task_path),
            "--output-format", "json", "--permission-mode", "dontAsk",
            "--allow", "Read", "--allow", "Write", "--allow", "Edit", "--allow", "Grep",
            "--allow", "Bash(python *)", "--allow", "Bash(grok *)",
            "--deny", "MCPTool", "--disable-web-search", "--no-subagents", "--max-turns", "30",
        ]
        stdin = None
    if args.model:
        command += ["--model", args.model]
    print(f"{args.provider}: セットアップを公式CLIへ依頼しました。ログ: {log_dir}", flush=True)
    started_ns = time.time_ns()
    result = _run_process(command, cwd=ROOT, env=_provider_environment(args.provider), timeout=args.timeout, input_text=stdin)
    (log_dir / "stdout.json").write_text(result.stdout, encoding="utf-8")
    (log_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    result_path = ROOT / "setup" / "results" / args.provider / "result.json"
    completed = False
    ready = False
    try:
        envelope = json.loads(result.stdout)
        finish = envelope.get("stopReason", envelope.get("stop_reason"))
        cli_finished = not envelope.get("is_error") and envelope.get("type") != "error" and (finish is None or finish in {"end_turn", "stop_sequence"})
        report = json.loads(result_path.read_text(encoding="utf-8"))
        completed = bool(cli_finished and result_path.stat().st_mtime_ns >= started_ns and report.get("provider") == args.provider and isinstance(report.get("ready"), bool))
        ready = completed and report["ready"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    print(json.dumps({"provider": args.provider, "exit_code": result.returncode, "timed_out": result.timed_out, "completed": completed, "ready": ready, "log_dir": str(log_dir), "result_path": str(result_path)}, ensure_ascii=False), flush=True)
    return result.returncode or (0 if ready and not result.timed_out else 2)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
