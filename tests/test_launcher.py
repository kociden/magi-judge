import builtins
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from magi import launcher

EXAMPLES = Path(__file__).parents[1] / "examples"


class LauncherTests(unittest.TestCase):
    def test_dragged_paths_lose_their_quotes(self):
        self.assertEqual(launcher.clean_path('  "C:\Game Jam\team01"  '), Path("C:\Game Jam\team01"))
        self.assertEqual(launcher.clean_path("'x/y'"), Path("x/y"))
        self.assertIsNone(launcher.clean_path("   "))

    def test_demo_builds_the_venue_screen_and_opens_it(self):
        with TemporaryDirectory() as tmp, patch.object(launcher, "RUNS", Path(tmp)), \
                patch.object(launcher.webbrowser, "open") as opened, patch("builtins.print"):
            launcher.demo()
            stages = list(Path(tmp).glob("demo-*/_award/stage.html"))
        self.assertEqual(len(stages), 1)
        self.assertTrue(opened.call_args[0][0].endswith("stage.html"))

    def test_single_entry_questions_become_a_judge_command(self):
        answers = iter([str(EXAMPLES / "tiny-game"), "", "見えないもの", f'"{EXAMPLES / "statement.txt"}"',
                        str(EXAMPLES / "transcript.txt"), "", "チームX"])
        with TemporaryDirectory() as tmp, patch.object(launcher, "RUNS", Path(tmp)), \
                patch.object(builtins, "input", lambda _: next(answers)), \
                patch.object(launcher.webbrowser, "open"), patch("builtins.print"):
            launcher.judge_one(use_ai=False)
            results = list(Path(tmp).glob("judge-*/result.json"))
            result = json.loads(results[0].read_text(encoding="utf-8"))
        self.assertEqual(result["title"], "tiny-game")
        self.assertTrue(result["demo"])
        self.assertEqual(sorted(e["path"] for e in result["evidence"] if e["kind"] == "claim"),
                         ["attachment/001-transcript.txt", "statement/001-statement.txt"])


if __name__ == "__main__":
    unittest.main()
