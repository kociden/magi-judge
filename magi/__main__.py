from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys

from .bundle import build_bundle
from .evidence import build_evidence_pack, evidence_index, fingerprint_media, render_evidence, scan_injection
from .judging import PERSONAS, aggregate, compare_runs, decision_schema, finalize_provider, make_prompt, protocol_record
from .providers import cli_version, grok_home, invoke, preflight
from .report import write_feedback, write_report, write_scores_csv, write_stage
from .rubric import DEFAULT_RUBRIC, PRODUCT_NAMES, validate_rubric, with_theme

MAX_SAMPLES = 5


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def demo_decision(provider: str, rubric: dict, pack: dict, sample: int = 1) -> dict:
    """A fixed, clearly fictional judgement that exercises every status."""
    ids = evidence_index(pack)
    source = next(i for i in ids.values() if i["kind"] == "source")
    play = next((i for i in ids.values() if i["kind"] == "play_record"), None)
    claim = next((i for i in ids.values() if i["kind"] == "claim"), None)
    # Vary by entry so a demo batch shows split votes, not identical ties.
    shift = (int(source["sha256"][:2], 16) % 5 - 2) * 0.5
    base = {"codex": 3.5, "claude": 3.0, "grok": 4.0}[provider] + shift + (0.5 if sample % 2 == 0 else 0)
    criteria = {}
    for offset, c in enumerate(rubric["criteria"]):
        cite_from = play if play and "play_record" in c.get("observed_requires", []) else source
        if c["id"] in ("experience", "ai_usage") and cite_from is source and not (c["id"] == "ai_usage" and claim):
            criteria[c["id"]] = {"status": "not_observed", "score": None, "rationale": "デモ: 判断できる資料がない想定です。", "limits": "", "evidence": []}
            continue
        cite = claim if c["id"] == "ai_usage" and claim else cite_from
        status = "observed" if cite["kind"] in c.get("observed_requires", []) else "inferred"
        criteria[c["id"]] = {
            "status": status, "score": min(5, max(0, base + (offset % 3 - 1) * 0.5)),
            "rationale": "デモ用の架空の採点です。作品の評価ではありません。",
            "limits": "" if status == "observed" else "デモ: ソースや主張からの推定という想定です。",
            "evidence": [{"evidence_id": cite["id"], "line_start": 1, "line_end": min(3, cite["line_count"]), "observation": "デモ用の固定の引用です。"}],
        }
    return {
        "criteria": criteria, "summary": f"デモ用の架空の講評です（{PERSONAS[provider]['role']}の目線）。モデルによる審査は行っていません。",
        "feedback": {"strengths": ["デモ: 良い点の表示確認用です。"], "suggestions": ["デモ: 改善提案の表示確認用です。"]},
        "integrity_flags": [], "uncertainties": ["全得点・理由はシミュレーションです。"],
    }


def _reusable(previous: dict | None, protocol: dict, bundle_digest: str, demo: bool) -> dict:
    """Successful judges from a previous attempt on identical inputs."""
    if not previous or previous.get("protocol", {}).get("digest") != protocol["digest"] or previous.get("bundle_digest") != bundle_digest or previous.get("demo") != demo:
        return {}
    return {r["provider"]: r for r in previous["results"] if r["status"] == "ok"}


def judge_entry(
    *, game: Path, title: str, rubric: dict, run_dir: Path, attachments: list[Path] = (), statements: list[Path] = (),
    play_records: list[Path] = (), media: list[Path] = (), redactions: list[str] = (), providers: list[str] = tuple(PERSONAS),
    models: dict | None = None, samples: int = 1, timeout: int = 180, demo: bool = False, previous: dict | None = None,
    attempt: int = 1, log=print,
) -> dict:
    models = models or {}
    bundle = build_bundle(game, title, list(attachments), statements=list(statements), play_records=list(play_records))
    if not bundle["files"]:
        raise ValueError("読めるゲームのテキストファイルがありません。bundleの対象拡張子を確認してください")
    pack = build_evidence_pack(bundle, fingerprint_media(list(media)))
    index = evidence_index(pack)
    protocol = protocol_record(rubric, models, samples)
    alias = f"作品-{bundle['content_digest'][:6].upper()}"
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    save_json(run_dir / "bundle.json", bundle)
    save_json(run_dir / "evidence.json", {**pack, "items": [{k: v for k, v in i.items() if k != "text"} for i in pack["items"]]})
    save_json(run_dir / "rubric.json", rubric)
    save_json(run_dir / "protocol.json", protocol)
    schema = decision_schema(rubric, list(index))
    save_json(run_dir / "schema.json", schema)
    nonce = secrets.token_hex(8)
    evidence_text, hidden = render_evidence(pack, nonce, list(redactions))
    host_flags = scan_injection(pack)
    reused = _reusable(previous, protocol, bundle["content_digest"], demo)
    log(f"MAGI / {title}（{alias}）\n資料 {len(pack['items'])} 件 / 省略 {len(bundle['omissions'])} 項目 / 観測: {pack['observation']['mode']}\n保存先: {run_dir}")
    if host_flags:
        log(f"要確認: 審査員への指示に見える記述が {len(host_flags)} か所あります。report.htmlで確認してください。")

    def run_provider(provider: str) -> list[dict]:
        out = []
        for sample in range(1, samples + 1):
            work_dir = run_dir / provider / f"sample-{sample}"
            prompt = make_prompt(provider, evidence_text, rubric, alias, nonce)
            if demo:
                work_dir.mkdir(parents=True)
                (work_dir / "judging-prompt.txt").write_text(prompt, encoding="utf-8")
                out.append({"provider": provider, "sample": sample, "status": "ok", "decision": demo_decision(provider, rubric, pack, sample), "error": None, "duration_seconds": 0, "model_requested": None})
                continue
            log(f"{PRODUCT_NAMES[provider]}: 審議開始（{sample}/{samples}）")
            response = invoke(provider, prompt, schema, work_dir, timeout, models.get(provider))
            out.append({**response, "sample": sample})
            if response["status"] != "ok":
                break  # A failed judge is held; extra samples cannot rescue it.
        return out

    pending = [p for p in providers if p not in reused]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {p: executor.submit(run_provider, p) for p in pending}
        sample_sets = {}
        for provider, future in futures.items():
            try:
                sample_sets[provider] = future.result()
            except Exception as exc:  # Reported as a held judge, never as a vote.
                sample_sets[provider] = [{"provider": provider, "status": "error", "decision": None, "error": str(exc)}]
    results = []
    for provider in PERSONAS:
        if provider in reused:
            # Keep pointing at the attempt that actually ran this judge.
            results.append({**reused[provider], "reused_from_attempt": reused[provider].get("reused_from_attempt") or previous.get("attempt", attempt - 1)})
        else:
            results.append(finalize_provider(provider, sample_sets.get(provider, []), rubric, index))
        log(f"{PRODUCT_NAMES[provider]}: {results[-1]['status']}")
    payload = {
        "kind": "judgment", "protocol": protocol, "created_at": datetime.now(timezone.utc).isoformat(), "demo": demo,
        "attempt": attempt, "title": title, "entry_alias": alias,
        "bundle_digest": bundle["content_digest"], "bundle_manifest_digest": bundle["digest"], "rubric": rubric,
        "observation": pack["observation"], "evidence": [{k: v for k, v in i.items() if k != "text"} for i in pack["items"]],
        "media": pack["media"], "host_integrity_flags": host_flags, "redactions_applied": hidden,
        "cli_versions": {} if demo else {p: cli_version(p) for p in providers},
        "results": results, "aggregate": aggregate(results), "limitations": bundle["limitations"],
        "included_count": len(pack["items"]), "omission_count": len(bundle["omissions"]),
    }
    save_json(run_dir / "result.json", payload)
    write_report(payload, run_dir / "report.html")
    write_feedback(payload, run_dir / "feedback.md")
    log(f"\n{payload['aggregate']['label']}: {payload['aggregate']['reason']}\n表示: {run_dir / 'report.html'}")
    return payload


def _rubric(args: argparse.Namespace, theme: str | None = None) -> dict:
    rubric = load_json(args.rubric) if args.rubric else DEFAULT_RUBRIC
    rubric = with_theme(rubric, args.theme if args.theme is not None else theme)
    validate_rubric(rubric)
    return rubric


def judge(args: argparse.Namespace) -> int:
    rubric = _rubric(args)
    run_dir = args.out or Path("runs") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    payload = judge_entry(
        game=args.game, title=args.title, rubric=rubric, run_dir=run_dir, attachments=args.attachment,
        statements=args.statement, play_records=args.play_record, media=args.media, redactions=args.redact,
        providers=args.providers, models=args.model, samples=args.samples, timeout=args.timeout, demo=args.demo,
        log=lambda text: print(text, flush=True),
    )
    return 2 if any(r["status"] != "ok" for r in payload["results"]) else 0


def _latest_attempt(entry_dir: Path) -> tuple[int, dict | None]:
    attempts = sorted((int(p.name.split("-", 1)[1]), p) for p in entry_dir.glob("attempt-*") if p.name.split("-", 1)[1].isdigit()) if entry_dir.is_dir() else []
    for number, path in reversed(attempts):
        if (path / "result.json").is_file():
            return attempts[-1][0], load_json(path / "result.json")
    return (attempts[-1][0] if attempts else 0), None


def batch(args: argparse.Namespace) -> int:
    """Judge a queue of entries; re-running resumes only what is unfinished."""
    manifest = load_json(args.entries)
    base = args.entries.resolve().parent
    rubric = _rubric(args, manifest.get("theme"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries.json に entries の配列が必要です")
    ids = [e.get("id") for e in entries]
    if any(not isinstance(i, str) or not i.replace("-", "").replace("_", "").isalnum() or not i.isascii() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("各entryのidは英数字・-・_で、重複なしにしてください")
    paths = lambda entry, key: [base / p for p in ([entry[key]] if isinstance(entry.get(key), str) else entry.get(key, []))]
    protocol = protocol_record(rubric, args.model, args.samples)
    latest = []
    for entry in entries:
        entry_dir = args.out / entry["id"]
        number, previous = _latest_attempt(entry_dir)
        done = previous and previous.get("demo") == args.demo and previous["protocol"]["digest"] == protocol["digest"] and all(r["status"] == "ok" for r in previous["results"])
        if done:
            bundle = build_bundle(base / entry["game"], entry["title"], paths(entry, "attachments"), statements=paths(entry, "statement"), play_records=paths(entry, "play_records"))
            done = bundle["content_digest"] == previous["bundle_digest"]
        if done:
            print(f"{entry['id']}: 完了済み（attempt-{number}）", flush=True)
            latest.append(previous)
            continue
        if number >= args.max_attempts:
            print(f"{entry['id']}: 試行上限 {args.max_attempts} 回に達したため保留。原因を確認してください。", flush=True)
            if previous:
                latest.append(previous)
            continue
        try:
            payload = judge_entry(
                game=base / entry["game"], title=entry["title"], rubric=rubric, run_dir=entry_dir / f"attempt-{number + 1}",
                attachments=paths(entry, "attachments"), statements=paths(entry, "statement"), play_records=paths(entry, "play_records"),
                media=paths(entry, "media"), redactions=entry.get("redact", []), providers=args.providers, models=args.model,
                samples=args.samples, timeout=args.timeout, demo=args.demo, previous=previous, attempt=number + 1,
                log=lambda text: print(text, flush=True),
            )
            latest.append(payload)
        except (ValueError, OSError) as exc:
            print(f"{entry['id']}: エラー {exc}", file=sys.stderr, flush=True)
    complete = len(latest) == len(entries) and all(all(r["status"] == "ok" for r in p["results"]) for p in latest)
    if not complete:
        print("\n未完了の作品があります。同じコマンドを再実行すると失敗分だけ再審査します。", flush=True)
        return 2
    if len(latest) >= 2:
        award_dir = args.out / "_award"
        award_dir.mkdir(parents=True, exist_ok=True)
        result = compare_runs(latest, args.allow_mixed_observation)
        save_json(award_dir / "result.json", result)
        write_report(result, award_dir / "report.html")
        write_scores_csv(latest, award_dir / "scores.csv")
        write_stage(result, latest, award_dir / "stage.html")
        print(f"\n{result['aggregate']['label']}\n表示: {(award_dir / 'report.html').resolve()}\n会場画面: {(award_dir / 'stage.html').resolve()}", flush=True)
    return 0


def _add_run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rubric", type=Path, help="採点設定JSON。省略時は同梱の仮設定")
    p.add_argument("--theme", help="当日のテーマ。テーマ項目の採点に必要")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--providers", nargs="+", choices=list(PERSONAS), default=list(PERSONAS))
    p.add_argument("--model", action="append", default=[], metavar="PROVIDER=MODEL")
    p.add_argument("--samples", type=int, default=1, help=f"各AIの採点回数（1〜{MAX_SAMPLES}）。平均してぶれを抑える")
    p.add_argument("--demo", action="store_true", help="固定の架空判定で表示を確認。モデルは呼び出さない")


def main() -> int:
    parser = argparse.ArgumentParser(description="MAGI / 公式CLIのサブスク認証を使うゲームジャム審査ハーネス")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("judge", help="1作品を3基で独立審査")
    p.add_argument("game", type=Path)
    p.add_argument("--title", required=True)
    p.add_argument("--attachment", type=Path, action="append", default=[], help="企画書・スライド・文字起こし（参加者の主張）")
    p.add_argument("--statement", type=Path, action="append", default=[], help="提出時の説明文（テーマとのつながり/遊び方/AIの工夫）")
    p.add_argument("--play-record", type=Path, action="append", default=[], help="運営が遊んだ共通プレイ記録")
    p.add_argument("--media", type=Path, action="append", default=[], help="スクショ・動画。記録のみで審査員には見せない")
    p.add_argument("--redact", action="append", default=[], help="審査員に見せない文字列（チーム名など）")
    p.add_argument("--out", type=Path)
    _add_run_options(p)
    p = sub.add_parser("batch", help="entries.jsonの全作品を審査。再実行で失敗分だけ再開")
    p.add_argument("entries", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--allow-mixed-observation", action="store_true")
    _add_run_options(p)
    p = sub.add_parser("compare", help="同じ条件で審査した作品の相対順位とMAGI賞候補")
    p.add_argument("results", type=Path, nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-mixed-observation", action="store_true", help="プレイ記録の有無が異なる作品の比較を明示的に許可")
    sub.add_parser("doctor", help="各CLIのサブスク認証の準備状態を確認")
    sub.add_parser("menu", help="番号で選ぶランチャー（コマンドを打たずに試せる）")
    args = parser.parse_args()
    try:
        if args.command == "menu":
            from .launcher import main as launcher_main
            return launcher_main()
        if args.command == "doctor":
            with ThreadPoolExecutor(max_workers=3) as executor:
                checks = list(executor.map(preflight, PERSONAS))
            for check in checks:
                print(f"{check['provider']}: {'READY' if check['subscription_ready'] else 'SETUP REQUIRED'} / {check.get('error') or 'サブスク認証確認済み'}")
                if check["provider"] == "grok":
                    print(f"  Grok専用領域: {grok_home()}")
                    if check.get("warning"):
                        print("  ログインの有効性は実際の呼び出し時にCLIが検証します。")
            return 0 if all(c["subscription_ready"] for c in checks) else 2
        if args.command == "compare":
            runs = [load_json(p) for p in args.results]
            result = compare_runs(runs, args.allow_mixed_observation)
            args.out.mkdir(parents=True, exist_ok=False)
            save_json(args.out / "result.json", result)
            write_report(result, args.out / "report.html")
            write_scores_csv(runs, args.out / "scores.csv")
            write_stage(result, runs, args.out / "stage.html")
            print(f"{result['aggregate']['label']}\n表示: {(args.out / 'report.html').resolve()}\n会場画面: {(args.out / 'stage.html').resolve()}")
            return 0
        if not 20 <= args.timeout <= 1800 or len(set(args.providers)) != len(args.providers):
            raise ValueError("timeoutは20〜1800秒、providersは重複なしにしてください")
        if not 1 <= args.samples <= MAX_SAMPLES:
            raise ValueError(f"--samples は1〜{MAX_SAMPLES}にしてください")
        models = {}
        for entry in args.model:
            provider, sep, model = entry.partition("=")
            if provider not in PERSONAS or not sep or not model.strip() or provider in models:
                raise ValueError("--model は codex=MODEL 等の形式で、重複なしにしてください")
            models[provider] = model
        args.model = models
        return batch(args) if args.command == "batch" else judge(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
