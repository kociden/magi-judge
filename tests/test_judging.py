import copy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from magi import __main__ as cli
from magi.evidence import evidence_index
from magi.judging import (
    HARNESS_VERSION, PERSONAS, aggregate, compare_runs, decision_schema, finalize_provider, make_prompt,
    merge_samples, persona_vote, protocol_record, totals, validate_decision,
)
from magi.report import write_feedback, write_report, write_scores_csv, write_stage
from magi.rubric import DEFAULT_RUBRIC, common_weights, judge_names, model_label, validate_rubric, with_theme

RUBRIC = with_theme(DEFAULT_RUBRIC, "見えないもの")
IDS = [c["id"] for c in RUBRIC["criteria"]]
PACK = {"items": [
    {"id": "F001", "kind": "source", "path": "index.html", "line_count": 20, "sha256": "x", "truncated": False, "text": "\n" * 19},
    {"id": "S001", "kind": "claim", "path": "statement/001-s.txt", "line_count": 3, "sha256": "y", "truncated": False, "text": "a\nb\nc"},
    {"id": "P001", "kind": "play_record", "path": "play/001-p.md", "line_count": 10, "sha256": "z", "truncated": False, "text": "\n" * 9},
], "media": [], "observation": {"mode": "play_record"}}
INDEX = evidence_index(PACK)


def criterion(status="observed", score=3.0, cite="P001", limits=""):
    evidence = [] if cite is None else [{"evidence_id": cite, "line_start": 1, "line_end": 2, "observation": "確認"}]
    return {"status": status, "score": score, "rationale": "理由", "limits": limits, "evidence": evidence}


def decision(score=3.0, **overrides):
    value = {
        "criteria": {cid: criterion(score=score) for cid in IDS}, "summary": "講評",
        "feedback": {"strengths": ["良い"], "suggestions": ["改善"]}, "integrity_flags": [], "uncertainties": [],
    }
    value["criteria"].update(overrides)
    return value


def provider_result(provider, score=3.0, **overrides):
    return finalize_provider(provider, [{"status": "ok", "decision": decision(score, **overrides)}], RUBRIC, INDEX)


def run(alias, scores, *, mode="play_record", demo=False, digest="p", overrides=None):
    results = [provider_result(p, s, **(overrides or {})) for p, s in zip(PERSONAS, scores)]
    return {
        "kind": "judgment", "title": alias, "entry_alias": alias, "bundle_digest": alias, "demo": demo,
        "protocol": {"harness_version": HARNESS_VERSION, "digest": digest}, "observation": {"mode": mode},
        "rubric": RUBRIC, "results": results, "aggregate": aggregate(results),
    }


class RubricTests(unittest.TestCase):
    def test_default_rubric_is_the_example_and_needs_a_theme(self):
        example = json.loads((Path(__file__).parents[1] / "rubric.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example, DEFAULT_RUBRIC)
        validate_rubric(RUBRIC)
        with self.assertRaisesRegex(ValueError, "--theme"):
            validate_rubric(DEFAULT_RUBRIC)

    def test_invalid_configurations_are_rejected(self):
        cases = [
            lambda r: r["criteria"][0]["anchors"].pop("4"),
            lambda r: r["criteria"][0].update(weight=25),
            lambda r: r["persona_weights"]["grok"].update(theme=99),
            lambda r: r["persona_weights"].update(gemini=r["persona_weights"]["grok"]),
            lambda r: r["criteria"][1].update(observed_requires=["claim"]),
            lambda r: r.update(recommendation_threshold=0),
        ]
        for mutate in cases:
            rubric = copy.deepcopy(RUBRIC)
            mutate(rubric)
            with self.assertRaises(ValueError):
                validate_rubric(rubric)


class DecisionValidationTests(unittest.TestCase):
    def test_valid_decision_round_trips(self):
        normalized, notes = validate_decision(decision(), RUBRIC, INDEX)
        self.assertEqual(notes, [])
        self.assertEqual(normalized["criteria"]["fun"]["status"], "observed")

    def test_unconfirmed_is_null_never_zero(self):
        validate_decision(decision(fun=criterion("not_observed", None, None)), RUBRIC, INDEX)
        for bad in (criterion("not_observed", 0, None), criterion("observed", None), criterion("inferred", None, limits="x")):
            with self.assertRaises(ValueError):
                validate_decision(decision(fun=bad), RUBRIC, INDEX)

    def test_scores_must_be_finite_and_in_range(self):
        for bad in (float("nan"), float("inf"), True, -1, 6, "3"):
            with self.assertRaises(ValueError):
                validate_decision(decision(fun=criterion(score=bad)), RUBRIC, INDEX)

    def test_fabricated_citations_are_rejected(self):
        for cite in (
            {"evidence_id": "F999", "line_start": 1, "line_end": 1, "observation": "x"},
            {"evidence_id": "F001", "line_start": 21, "line_end": None, "observation": "x"},
            {"evidence_id": "F001", "line_start": 5, "line_end": 2, "observation": "x"},
            {"evidence_id": "F001", "line_start": 0, "line_end": 1, "observation": "x"},
            {"evidence_id": "F001", "line_start": 1, "line_end": 1, "observation": " "},
        ):
            item = criterion()
            item["evidence"] = [cite]
            with self.assertRaises(ValueError):
                validate_decision(decision(fun=item), RUBRIC, INDEX)
        bad = decision()
        bad["integrity_flags"] = [{"evidence_id": "X001", "line_start": None, "description": "x"}]
        with self.assertRaises(ValueError):
            validate_decision(bad, RUBRIC, INDEX)

    def test_scored_items_need_citations_and_inferences_need_limits(self):
        with self.assertRaises(ValueError):
            validate_decision(decision(fun=criterion(cite=None)), RUBRIC, INDEX)
        with self.assertRaises(ValueError):
            validate_decision(decision(fun=criterion("inferred", 3, "F001", limits="")), RUBRIC, INDEX)

    def test_observed_from_the_wrong_evidence_kind_is_downgraded_with_a_note(self):
        # Fun can only be observed from a play record; source and claims are inferences.
        normalized, notes = validate_decision(decision(fun=criterion(cite="F001"), ai_usage=criterion(cite="S001")), RUBRIC, INDEX)
        self.assertEqual(normalized["criteria"]["fun"]["status"], "inferred")
        self.assertEqual(normalized["criteria"]["ai_usage"]["status"], "inferred")
        self.assertIn("ホストが推定に変更", normalized["criteria"]["fun"]["limits"])
        self.assertEqual(len(notes), 2)
        self.assertEqual(normalized["criteria"]["theme"]["status"], "observed")


class TallyTests(unittest.TestCase):
    def test_missing_items_are_not_rescaled(self):
        combined = merge_samples([decision(5, ai_usage=criterion("not_observed", None, None))], RUBRIC)
        bounds = totals(combined, common_weights(RUBRIC))
        self.assertIsNone(bounds["total"])
        self.assertEqual((bounds["lower"], bounds["upper"], bounds["coverage"]), (90, 100, 0.9))

    def test_samples_are_averaged_and_majority_null_stays_unconfirmed(self):
        nulls = criterion("not_observed", None, None)
        combined = merge_samples([decision(2), decision(4), decision(3, fun=nulls)], RUBRIC)
        self.assertEqual(combined["theme"]["score"], 3)
        self.assertEqual(combined["theme"]["spread"], 2)
        self.assertEqual(combined["fun"]["score"], 3)
        combined = merge_samples([decision(2, fun=nulls), decision(4, fun=nulls), decision(3)], RUBRIC)
        self.assertIsNone(combined["fun"]["score"])

    def test_vote_is_computed_by_the_host_from_bounds(self):
        self.assertEqual(persona_vote(merge_samples([decision(4)], RUBRIC), RUBRIC, "codex")[0], "approve")
        self.assertEqual(persona_vote(merge_samples([decision(2)], RUBRIC), RUBRIC, "codex")[0], "reject")
        missing_required = merge_samples([decision(5, fun=criterion("not_observed", None, None))], RUBRIC)
        vote, reason = persona_vote(missing_required, RUBRIC, "codex")
        self.assertEqual(vote, "abstain")
        self.assertIn("面白さの芯", reason)
        straddle = merge_samples([decision(3.5, theme=criterion("not_observed", None, None))], RUBRIC)
        self.assertEqual(persona_vote(straddle, RUBRIC, "codex")[0], "abstain")
        hopeless = merge_samples([decision(1, theme=criterion("not_observed", None, None))], RUBRIC)
        self.assertEqual(persona_vote(hopeless, RUBRIC, "codex")[0], "reject")

    def test_persona_weights_change_only_that_judges_total(self):
        scores = {"theme": 5, "fun": 3, "experience": 2, "completeness": 2, "ai_usage": 3}
        overrides = {cid: criterion(score=s) for cid, s in scores.items()}
        casper, melchior = provider_result("grok", **overrides), provider_result("codex", **overrides)
        self.assertEqual(casper["common"], melchior["common"])
        self.assertGreater(casper["persona"]["total"], melchior["persona"]["total"])

    def test_majority_abstention_and_failures(self):
        unanimous = aggregate([provider_result(p, 4) for p in PERSONAS])
        self.assertTrue(unanimous["unanimous"])
        self.assertEqual(unanimous["label"], "全会一致で可決")
        results = [provider_result("codex", 4), provider_result("claude", 4), provider_result("grok", 1)]
        self.assertEqual(aggregate(results)["state"], "APPROVED")
        self.assertNotIn("unanimous", aggregate(results))
        self.assertEqual(aggregate(results)["seat_score"], 60)
        results[2] = provider_result("grok", 1)
        results[1] = provider_result("claude", 1)
        self.assertEqual(aggregate(results)["state"], "REJECTED")
        unconfirmed = criterion("not_observed", None, None)
        held = [provider_result("codex", 4), provider_result("claude", 4), provider_result("grok", 4, fun=unconfirmed)]
        self.assertEqual(aggregate(held)["state"], "APPROVED")
        held[1] = provider_result("claude", 1)
        self.assertEqual(aggregate(held)["hold_kind"], "insufficient_observation")
        broken = finalize_provider("grok", [{"status": "error", "decision": None, "error": "timeout"}], RUBRIC, INDEX)
        self.assertEqual(aggregate([results[0], results[1], broken])["hold_kind"], "system")
        self.assertEqual(aggregate(results[:2])["hold_kind"], "system")

    def test_invalid_output_becomes_a_system_hold_not_a_vote(self):
        bad = decision()
        bad["criteria"]["fun"]["evidence"][0]["evidence_id"] = "F404"
        result = finalize_provider("codex", [{"status": "ok", "decision": bad}], RUBRIC, INDEX)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("vote", result)
        second_fails = finalize_provider("codex", [{"status": "ok", "decision": decision()}, {"status": "error", "error": "rate limit"}], RUBRIC, INDEX)
        self.assertEqual(second_fails["status"], "error")


class ComparisonTests(unittest.TestCase):
    def test_three_matching_picks_are_unanimous(self):
        result = compare_runs([run("a", [4, 4, 4]), run("b", [2, 2, 2])])
        self.assertEqual((result["aggregate"]["mode"], result["aggregate"]["winners"]), ("unanimous", ["a"]))
        self.assertEqual(result["aggregate"]["votes"], {"a": 3})

    def test_two_picks_win_by_majority(self):
        result = compare_runs([run("a", [5, 5, 1]), run("b", [1, 1, 5])])
        self.assertEqual((result["aggregate"]["mode"], result["aggregate"]["winners"]), ("majority", ["a"]))
        self.assertEqual([p["winner"]["alias"] for p in result["picks"]], ["a", "a", "b"])

    def test_split_picks_fall_back_to_the_best_average_among_the_picked(self):
        # "d" has the best average but no judge picked it, so it cannot win.
        runs = [run("a", [5, 1.5, 1]), run("b", [1, 5, 1]), run("c", [1, 1, 5]), run("d", [3, 3, 3])]
        result = compare_runs(runs)
        self.assertEqual([p["winner"]["alias"] for p in result["picks"]], ["a", "b", "c"])
        self.assertEqual((result["aggregate"]["mode"], result["aggregate"]["winners"]), ("average", ["a"]))
        self.assertIn("割れた", result["aggregate"]["reason"])

    def test_equal_averages_share_the_award(self):
        result = compare_runs([run("a", [5, 1, 1]), run("b", [1, 5, 1]), run("c", [1, 1, 5])])
        self.assertEqual(sorted(result["aggregate"]["winners"]), ["a", "b", "c"])
        self.assertIn("共同受賞", result["aggregate"]["reason"])

    def test_tied_picks_abstain_and_the_award_still_resolves(self):
        result = compare_runs([run("a", [3, 3, 3]), run("b", [3, 3, 3])])
        self.assertTrue(all(p["kind"] == "tie" for p in result["picks"]))
        self.assertEqual(sorted(result["aggregate"]["winners"]), ["a", "b"])

    def test_unconfirmed_entry_that_could_win_holds_the_award(self):
        partial = run("b", [3, 3, 3], overrides={"ai_usage": criterion("not_observed", None, None)})
        held = compare_runs([run("a", [3.1, 3.1, 3.1]), partial])
        self.assertTrue(all(p["kind"] == "insufficient_observation" for p in held["picks"]))
        self.assertEqual(held["aggregate"]["label"], "審議保留（観測不足）")
        clear = compare_runs([run("a", [4, 4, 4]), run("b", [1, 1, 1], overrides={"ai_usage": criterion("not_observed", None, None)})])
        self.assertEqual(clear["aggregate"]["winners"], ["a"])

    def test_failed_judge_holds_the_award(self):
        b = run("b", [1, 1, 1])
        b["results"][0] = finalize_provider("codex", [{"status": "error", "error": "x"}], RUBRIC, INDEX)
        b["aggregate"] = aggregate(b["results"])
        result = compare_runs([run("a", [4, 4, 4]), b])
        self.assertEqual(result["aggregate"]["label"], "審議保留（システム）")

    def test_incomparable_results_are_refused(self):
        with self.assertRaisesRegex(ValueError, "異なる"):
            compare_runs([run("a", [3, 3, 3]), run("b", [3, 3, 3], digest="other")])
        with self.assertRaisesRegex(ValueError, "デモ"):
            compare_runs([run("a", [3, 3, 3]), run("b", [3, 3, 3], demo=True)])
        with self.assertRaisesRegex(ValueError, "重複"):
            compare_runs([run("a", [3, 3, 3]), run("a", [3, 3, 3])])
        mixed = [run("a", [3, 3, 3]), run("b", [2, 2, 2], mode="source_only")]
        with self.assertRaisesRegex(ValueError, "プレイ記録"):
            compare_runs(mixed)
        self.assertEqual(compare_runs(mixed, allow_mixed_observation=True)["observation_modes"], ["play_record", "source_only"])
        legacy = run("b", [3, 3, 3])
        legacy["protocol"] = {"digest": "p"}
        with self.assertRaises(ValueError):
            compare_runs([run("a", [3, 3, 3]), legacy])


class ProtocolTests(unittest.TestCase):
    def test_prompt_hides_identity_and_weights(self):
        prompt = make_prompt("grok", "<<<EVIDENCE F001 n>>>", RUBRIC, "作品-ABC", "n")
        self.assertIn("作品-ABC", prompt)
        self.assertIn("見えないもの", prompt)
        self.assertIn("CASPER", prompt)
        self.assertNotIn("persona_weights", prompt)
        self.assertNotIn("recommendation_threshold", prompt)

    def test_prompt_carries_nothing_about_the_award(self):
        # Judges score one game on its own; picks, votes and ranking stay host-side.
        prompt = make_prompt("codex", "<<<EVIDENCE F001 n>>>", RUBRIC, "作品-ABC", "n")
        for word in ("MAGI賞", "議案", "推し", "多数決", "全会一致", "平均点", RUBRIC["motion"]):
            self.assertNotIn(word, prompt)

    def test_schema_restricts_citations_and_allows_null_scores(self):
        schema = decision_schema(RUBRIC, ["F001", "P001"])
        item = schema["properties"]["criteria"]["properties"]["fun"]
        self.assertEqual(item["properties"]["score"]["type"], ["number", "null"])
        self.assertEqual(item["properties"]["evidence"]["items"]["properties"]["evidence_id"]["enum"], ["F001", "P001"])
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_protocol_digest_tracks_every_comparable_setting(self):
        base = protocol_record(RUBRIC, {}, 1)
        self.assertEqual(base, protocol_record(copy.deepcopy(RUBRIC), {}, 1))
        changed = copy.deepcopy(RUBRIC)
        changed["recommendation_threshold"] = 80
        for other in (protocol_record(changed, {}, 1), protocol_record(RUBRIC, {"grok": "grok-4.7"}, 1), protocol_record(RUBRIC, {}, 3)):
            self.assertNotEqual(base["digest"], other["digest"])


EXAMPLES = Path(__file__).parents[1] / "examples"


class EndToEndTests(unittest.TestCase):
    def judge(self, out, **kwargs):
        options = dict(game=EXAMPLES / "tiny-game", title="10秒ぴったり", rubric=RUBRIC, run_dir=out,
                       statements=[EXAMPLES / "statement.txt"], play_records=[EXAMPLES / "play-record.md"], demo=True, log=lambda _: None)
        options.update(kwargs)
        return cli.judge_entry(**options)

    def test_demo_run_writes_traceable_outputs(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            payload = self.judge(out, samples=2, redactions=["10秒ぴったり"])
            for name in ("bundle.json", "evidence.json", "protocol.json", "schema.json", "rubric.json", "result.json", "report.html", "feedback.md"):
                self.assertTrue((out / name).is_file(), name)
            prompt = (out / "grok" / "sample-2" / "judging-prompt.txt").read_text(encoding="utf-8")
            self.assertNotIn("10秒ぴったり", prompt)
            self.assertGreater(payload["redactions_applied"], 0)
            self.assertEqual(payload["observation"]["mode"], "play_record")
            self.assertTrue(all(len(r["samples"]) == 2 for r in payload["results"]))
            self.assertEqual(payload["protocol"]["samples_per_judge"], 2)

    def test_unselected_judge_holds_the_entry(self):
        with TemporaryDirectory() as tmp:
            payload = self.judge(Path(tmp) / "run", providers=["codex", "claude"])
        self.assertEqual(payload["aggregate"]["hold_kind"], "system")

    def test_retry_reuses_only_successful_judges_on_identical_inputs(self):
        calls = []

        def fake_invoke(provider, prompt, schema, work_dir, timeout, model):
            calls.append(provider)
            if provider == "codex" and calls.count("codex") == 1:
                return {"provider": provider, "status": "error", "decision": None, "error": "timed out"}
            pack = {"items": [{"id": i, "kind": k, "line_count": 3, "sha256": "00"} for i, k in (("F001", "source"), ("P001", "play_record"), ("S001", "claim"))]}
            return {"provider": provider, "status": "ok", "decision": cli.demo_decision(provider, RUBRIC, pack), "error": None}

        with TemporaryDirectory() as tmp, patch.object(cli, "invoke", fake_invoke), patch.object(cli, "cli_version", return_value="test"):
            first = self.judge(Path(tmp) / "a1", demo=False)
            self.assertEqual(first["aggregate"]["hold_kind"], "system")
            second = self.judge(Path(tmp) / "a2", demo=False, previous=first, attempt=2)
        self.assertEqual(sorted(calls), ["claude", "codex", "codex", "grok"])
        self.assertTrue(all(r["status"] == "ok" for r in second["results"]))
        self.assertEqual([r.get("reused_from_attempt") for r in second["results"]], [None, 1, 1])

    def test_batch_resumes_and_writes_award(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("one", "two"):
                (root / name).mkdir()
                (root / name / "index.html").write_text(f"<button>{name}</button>\n", encoding="utf-8")
            (root / "entries.json").write_text(json.dumps({"theme": "見えないもの", "entries": [
                {"id": "one", "title": "One", "game": "one"}, {"id": "two", "title": "Two", "game": "two"}]}), encoding="utf-8")
            argv = ["magi", "batch", str(root / "entries.json"), "--out", str(root / "out"), "--demo"]
            with patch("sys.argv", argv), patch("builtins.print"):
                self.assertEqual(cli.main(), 0)
                self.assertEqual(cli.main(), 0)
            self.assertFalse((root / "out" / "one" / "attempt-2").exists())
            with (root / "out" / "_award" / "scores.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual([r[0] for r in rows[1:]], ["One", "Two"])


class ReportTests(unittest.TestCase):
    def test_reports_escape_submission_content(self):
        data = run('<script>alert("x")</script>', [3, 3, 3])
        data.update(created_at="", attempt=1, evidence=[{"id": "F001", "path": "<img src=x>"}], media=[], limitations=[],
                    host_integrity_flags=[{"evidence_id": "F001", "path": "<b>", "line": 1, "patterns": ["得点の要求"], "excerpt": "<script>bad()</script>"}])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            write_report(data, path)
            text = path.read_text(encoding="utf-8")
            write_feedback(data, Path(tmp) / "feedback.md")
            write_scores_csv([data], Path(tmp) / "scores.csv")
            comparison = compare_runs([data, run("b", [1, 1, 1])])
            write_report(comparison, Path(tmp) / "award.html")
            write_stage(comparison, [data, run("b", [1, 1, 1])], Path(tmp) / "stage.html")
            stage = (Path(tmp) / "stage.html").read_text(encoding="utf-8")
        # Submitted titles reach the stage only as escaped JSON data, read via textContent.
        self.assertNotIn("<script>alert", stage)
        self.assertIn(r"\u003cscript\u003ealert", stage)
        self.assertNotIn("innerHTML", stage)
        self.assertNotIn("<script>", text)
        self.assertNotIn("<img src=x>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("要確認", text)


class ModelNameTests(unittest.TestCase):
    def test_model_ids_become_stage_names(self):
        cases = {("claude-opus-5-5", "claude"): "Opus 5.5", ("claude-sonnet-5-5", "claude"): "Sonnet 5.5",
                 ("claude-opus-4-8[1m]", "claude"): "Opus 4.8", ("claude-haiku-4-5-20251001", "claude"): "Haiku 4.5",
                 ("gpt-6.1-sol", "codex"): "GPT-6.1 Sol", ("grok-4.7", "grok"): "Grok 4.7",
                 ("grok-4.7-fast", "grok"): "Grok 4.7 Fast", (None, "codex"): "ChatGPT", ("odd-model", "grok"): "odd-model"}
        for (model, provider), expected in cases.items():
            self.assertEqual(model_label(model, provider), expected)

    def test_names_come_from_the_models_actually_used(self):
        data = run("a", [3, 3, 3])
        data["results"][1]["samples"][0]["model_used"] = "claude-opus-5-5"
        self.assertEqual(judge_names([data]), {"codex": "ChatGPT", "claude": "Opus 5.5", "grok": "Grok"})

    def test_stage_names_models_and_ranks_every_entry(self):
        runs = [run("a", [5, 5, 1]), run("b", [1, 1, 5]), run("c", [2, 2, 2])]
        for r in runs:
            r["results"][2]["samples"][0]["model_used"] = "grok-4.7"
        comparison = compare_runs(runs)
        self.assertEqual(comparison["judge_names"]["grok"], "Grok 4.7")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "stage.html"
            write_stage(comparison, runs, path)
            text = path.read_text(encoding="utf-8")
        data = json.loads(text.split("id='magi-data'>", 1)[1].split("</script>", 1)[0])
        self.assertEqual([b["title"] for b in data["board"]], ["a", "b", "c"])
        self.assertTrue(data["board"][0]["won"])
        self.assertEqual(data["board"][0]["pickedBy"], ["ChatGPT", "Claude"])
        self.assertIn("Grok 4.7", text)
        self.assertNotIn("MELCHIOR", text)


if __name__ == "__main__":
    unittest.main()
