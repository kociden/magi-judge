"""Numbered menu for people who would rather not type commands.

Every action runs the regular `python -m magi ...` command, so the same
validation and safeguards apply; the menu only collects answers and opens the
results afterwards.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DEMO_ENTRIES = ROOT / "examples" / "mock-jam" / "entries.json"

MENU = """
==============================
  MAGI SYSTEM ／ ランチャー
==============================
  1. 準備状態を確認する（3つのAIにログインできているか）
  2. デモを見る（AIを使わない架空の審査。すぐ終わる）
  3. 1作品を審査する
  4. 全作品をまとめて審査する（entries.json）
  5. これまでの結果を開く
  6. AIにログインする
  0. 終了
"""


def clean_path(text: str) -> Path | None:
    """Accept paths pasted or dragged into the console, with or without quotes."""
    text = text.strip().strip('"').strip("'").strip()
    return Path(text).expanduser() if text else None


def ask(prompt: str, default: str = "") -> str:
    suffix = f"（Enterで「{default}」）" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def ask_path(prompt: str, *, required: bool = True, folder: bool = False) -> Path | None:
    while True:
        path = clean_path(input(f"{prompt}: "))
        if path is None:
            if not required:
                return None
            print("  入力してください（ファイルやフォルダをこの画面にドラッグしても入力できます）。")
            continue
        if folder and path.is_dir() or not folder and path.is_file():
            return path
        print(f"  見つかりません: {path}")


def ask_yes(prompt: str, default: bool = False) -> bool:
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer in ("y", "yes", "はい")


def run_magi(*args: str) -> int:
    command = [sys.executable, "-m", "magi", *args]
    print("\n> python -m magi " + " ".join(f'"{a}"' if " " in a else a for a in args) + "\n")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def open_file(path: Path) -> None:
    if path.is_file():
        print(f"開きます: {path}")
        webbrowser.open(path.resolve().as_uri())
    else:
        print(f"結果のファイルがありません: {path}")


def new_out(label: str) -> Path:
    return RUNS / f"{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def demo() -> None:
    out = new_out("demo")
    print("架空の判定で、会場画面までの流れを確認します。AIは呼びません。")
    run_magi("batch", str(DEMO_ENTRIES), "--out", str(out), "--demo")
    open_file(out / "_award" / "stage.html")
    print("会場画面は Space で進みます（F で全画面）。")


def judge_one(use_ai: bool | None = None) -> None:
    game = ask_path("ゲームのフォルダ（Unityなら自作スクリプトのフォルダ）", folder=True)
    title = ask("作品名", game.name)
    theme = ask("当日のテーマ")
    while not theme:
        theme = ask("テーマは必須です。当日のテーマ")
    statement = ask_path("3行の説明のファイル", required=True)
    attachments = []
    print("発表資料・文字起こしのファイルを1つずつ入力（PPTX/PDF/TXT/MD）。終わったら空のままEnter。")
    while True:
        path = ask_path(f"  資料 {len(attachments) + 1}", required=False)
        if path is None:
            break
        attachments.append(path)
    if not attachments:
        print("  ※ 発表資料も文字起こしもないため、アイデアの評価は推定どまりになります。")
    team = ask("審査AIに伏せるチーム名（なければEnter）")
    if use_ai is None:
        use_ai = ask_yes("実際の3つのAIで審査しますか（いいえ＝架空のデモ）", default=True)
    out = new_out("judge")
    args = ["judge", str(game), "--title", title, "--theme", theme, "--statement", str(statement), "--out", str(out)]
    for path in attachments:
        args += ["--attachment", str(path)]
    if team:
        args += ["--redact", team]
    if not use_ai:
        args.append("--demo")
    else:
        print("3つのAIで審査します。1作品で数分かかります（Grokは約2分）。")
    run_magi(*args)
    open_file(out / "report.html")


def judge_all() -> None:
    entries = ask_path("作品一覧（entries.json）。書き方は examples/entries.json")
    use_ai = ask_yes("実際の3つのAIで審査しますか（いいえ＝架空のデモ）", default=True)
    default_out = RUNS / f"event-{entries.stem}"
    out = clean_path(ask("結果の保存先", str(default_out))) or default_out
    args = ["batch", str(entries), "--out", str(out)]
    if not use_ai:
        args.append("--demo")
    else:
        print("途中で止まっても、同じ保存先でもう一度実行すれば失敗した分だけ審査し直します。")
    code = run_magi(*args)
    if (out / "_award" / "stage.html").is_file():
        open_file(out / "_award" / "stage.html")
        print("会場画面は Space で進みます（F で全画面）。MAGI賞の記録は _award/report.html です。")
    elif code:
        print("全作品の審査がそろっていないため、会場画面はまだ作られていません。")


def open_results() -> None:
    found = sorted(
        (p for p in RUNS.glob("*/**/*.html") if p.name in ("stage.html", "report.html")),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:15] if RUNS.is_dir() else []
    if not found:
        print("まだ結果がありません。")
        return
    for n, path in enumerate(found, start=1):
        kind = "会場画面" if path.name == "stage.html" else "審査結果"
        print(f"  {n:2}. {kind}  {path.parent.relative_to(RUNS)}")
    choice = ask("開く番号（Enterで戻る）")
    if choice.isdigit() and 1 <= int(choice) <= len(found):
        open_file(found[int(choice) - 1])


def login() -> None:
    from .providers import grok_home
    print("""
  1. ChatGPT（Codex）にログイン
  2. Claude（Claude Code）にログイン
  3. Grok（MAGI専用の保存場所）にログイン
  0. 戻る
ブラウザが開いたら、自分のアカウントでサインインしてください。APIキーは使いません。""")
    choice = ask("番号")
    if choice == "1":
        subprocess.run(["codex", "login"], check=False, shell=os.name == "nt")
    elif choice == "2":
        subprocess.run(["claude", "auth", "login"], check=False, shell=os.name == "nt")
    elif choice == "3":
        home = grok_home()
        home.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GROK_HOME": str(home)}
        subprocess.run(["grok", "login", "--oauth"], check=False, env=env, shell=os.name == "nt")


ACTIONS = {"1": lambda: run_magi("doctor"), "2": demo, "3": judge_one, "4": judge_all, "5": open_results, "6": login}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    while True:
        print(MENU)
        try:
            choice = input("番号を選んでください: ").replace("\ufeff", "").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice == "0":
            return 0
        action = ACTIONS.get(choice)
        if not action:
            print("0〜6の番号を入力してください。")
            continue
        try:
            action()
        except KeyboardInterrupt:
            print("\n中止しました。")
        except EOFError:
            return 0
        input("\nEnterでメニューに戻ります。")


if __name__ == "__main__":
    raise SystemExit(main())
