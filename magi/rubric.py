"""Editable scoring configuration and the three fixed judging personas."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re

# Personas change what each judge comments on, never the criteria, anchors or
# evidence it is given. Persona weights, if configured, are applied by the host.
PERSONAS = {
    "codex": {
        "name": "MELCHIOR・1", "role": "科学者",
        "view": "作り手・技術の目線。完成度とAIの使い方、仕組みと根拠の整合性に特に注目する。",
    },
    "claude": {
        "name": "BALTHASAR・2", "role": "母",
        "view": "初めて遊ぶプレイヤーを見守る目線。わかりやすさ、操作の手触り、体験の流れに特に注目する。",
    },
    "grok": {
        "name": "CASPER・3", "role": "女",
        "view": "審美眼の目線。テーマの切り口、驚き、世界観と記憶に残る魅力に特に注目する。",
    },
}

EVIDENCE_KINDS = ("source", "play_record", "claim")
ANCHOR_KEYS = tuple(str(i) for i in range(6))
DEFAULT_RUBRIC_PATH = Path(__file__).with_name("default_rubric.json")


def load_default_rubric() -> dict:
    return json.loads(DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8"))


DEFAULT_RUBRIC = load_default_rubric()


def _positive_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _check_weights(weights: object, ids: list[str], label: str) -> None:
    if not isinstance(weights, dict) or set(weights) != set(ids):
        raise ValueError(f"{label}: 全項目の配点を指定してください")
    if not all(_positive_number(w) for w in weights.values()):
        raise ValueError(f"{label}: 配点は正の数にしてください")
    if not math.isclose(sum(weights.values()), 100):
        raise ValueError(f"{label}: 配点の合計は100にしてください")


def validate_rubric(rubric: dict) -> None:
    if not isinstance(rubric, dict) or not isinstance(rubric.get("motion"), str) or not rubric["motion"].strip():
        raise ValueError("rubric.motion は空でない文字列にしてください")
    theme = rubric.get("theme")
    if theme is not None and (not isinstance(theme, str) or not theme.strip()):
        raise ValueError("rubric.theme は空でない文字列かnullにしてください")
    threshold = rubric.get("recommendation_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold <= 100:
        raise ValueError("recommendation_threshold は0より大きく100以下の数にしてください")
    strictness = rubric.get("strictness")
    if strictness is not None and (not isinstance(strictness, str) or not strictness.strip()):
        raise ValueError("strictness は空でない文字列かnullにしてください")
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 12:
        raise ValueError("採点項目は1〜12項目にしてください")
    ids = []
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("採点項目の形式が不正です")
        cid = criterion.get("id")
        if not isinstance(cid, str) or not cid.isascii() or not cid.replace("_", "").isalnum():
            raise ValueError("項目idは英数字とアンダースコアにしてください")
        ids.append(cid)
        for key in ("label", "description"):
            if not isinstance(criterion.get(key), str) or not criterion[key].strip():
                raise ValueError(f"{cid}: {key}が必要です")
        anchors = criterion.get("anchors")
        if not isinstance(anchors, dict) or set(anchors) != set(ANCHOR_KEYS) or not all(isinstance(v, str) and v.strip() for v in anchors.values()):
            raise ValueError(f"{cid}: anchorsに0〜5点それぞれの具体例が必要です")
        for flag in ("required", "requires_theme"):
            if not isinstance(criterion.get(flag, False), bool):
                raise ValueError(f"{cid}: {flag}は真偽値にしてください")
        kinds = criterion.get("observed_requires", ["source", "play_record"])
        if not isinstance(kinds, list) or not kinds or not set(kinds) <= {"source", "play_record"}:
            raise ValueError(f"{cid}: observed_requires は source / play_record から選んでください。参加者の主張だけでは観測済みにできません")
        if criterion.get("requires_theme") and theme is None:
            raise ValueError(f"「{criterion['label']}」の採点には当日のテーマが必要です。--theme で指定してください")
    if len(set(ids)) != len(ids):
        raise ValueError("項目idは重複できません")
    _check_weights({c["id"]: c.get("weight") for c in criteria}, ids, "共通配点")
    persona_weights = rubric.get("persona_weights")
    if persona_weights is not None:
        if not isinstance(persona_weights, dict) or not set(persona_weights) <= set(PERSONAS):
            raise ValueError("persona_weights のキーは codex / claude / grok にしてください")
        for provider, weights in persona_weights.items():
            _check_weights(weights, ids, f"{PERSONAS[provider]['name']}の配点")


def with_theme(rubric: dict, theme: str | None) -> dict:
    result = copy.deepcopy(rubric)
    if theme is not None:
        result["theme"] = theme.strip() or None
    return result


def common_weights(rubric: dict) -> dict[str, float]:
    return {c["id"]: c["weight"] for c in rubric["criteria"]}


def persona_weights(rubric: dict, provider: str) -> dict[str, float]:
    return (rubric.get("persona_weights") or {}).get(provider) or common_weights(rubric)


PRODUCT_NAMES = {"codex": "ChatGPT", "claude": "Claude", "grok": "Grok"}


def model_label(model_id: str | None, provider: str) -> str:
    """Stage name for a model ID: claude-opus-5-5 -> Opus 5.5, gpt-6.1-sol ->
    GPT-6.1 Sol, grok-4.7 -> Grok 4.7. Unknown models show the product name."""
    if not model_id:
        return PRODUCT_NAMES[provider]
    name = re.sub(r"\[[^\]]*\]$", "", model_id.strip())
    claude = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?", name)
    if claude:
        family, major, minor = claude.groups()
        return f"{family.capitalize()} {major}{'.' + minor if minor else ''}"
    gpt = re.fullmatch(r"gpt-([\d.]+[a-z]?)((?:-[a-z0-9]+)*)", name, re.I)
    if gpt:
        extra = " ".join(part.capitalize() for part in gpt.group(2).split("-") if part)
        return f"GPT-{gpt.group(1)}" + (f" {extra}" if extra else "")
    grok = re.fullmatch(r"grok-([\d.]+)((?:-[a-z0-9]+)*)", name, re.I)
    if grok:
        extra = " ".join(part.capitalize() for part in grok.group(2).split("-") if part)
        return f"Grok {grok.group(1)}" + (f" {extra}" if extra else "")
    return name


def judge_names(runs: list[dict]) -> dict[str, str]:
    """One stage name per judge, from the model each CLI reported running."""
    from collections import Counter
    names = {}
    for provider in PERSONAS:
        used = Counter(
            sample.get("model_used") for run in runs for result in run["results"]
            if result["provider"] == provider for sample in result.get("samples", []) if sample.get("model_used")
        )
        names[provider] = model_label(used.most_common(1)[0][0] if used else None, provider)
    return names


def models_used(runs: list[dict]) -> dict[str, list[str]]:
    return {p: sorted({s["model_used"] for run in runs for r in run["results"] if r["provider"] == p
                       for s in r.get("samples", []) if s.get("model_used")}) for p in PERSONAS}
