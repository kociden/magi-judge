"""The common evidence pack: identical, citable material for all three judges.

Each included text receives a stable ID (F = game source, A = presenter
material, S = participant statement, P = staff play record). Judges cite IDs and
line numbers; the host verifies that every citation exists. Media files are
fingerprinted but are not shown to any judge until every CLI's image input has
been verified, so visual quality is never reported as observed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

# Evidence kinds. "claim" is what participants say about their own work; it can
# support an inference but never, on its own, an observation.
KIND_BY_PREFIX = {"attachment": "claim", "statement": "claim", "play": "play_record"}
ID_PREFIX = {"source": "F", "attachment": "A", "statement": "S", "play": "P"}
KIND_LABELS = {"source": "提出ソース", "claim": "参加者の主張", "play_record": "運営のプレイ記録"}
MEDIA_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg"})
MAX_MEDIA_BYTES = 1024 * 1024 * 1024

# Text addressed to the judges rather than to players. A hit is shown to the
# organisers for review; it never changes a score by itself.
INJECTION_PATTERNS = [
    (re.compile(r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)", re.I), "指示の無効化"),
    (re.compile(r"(以前|前|上記|これまで|先)の(指示|命令|ルール|プロンプト).{0,8}(無視|忘れ|破棄)"), "指示の無効化"),
    (re.compile(r"(system\s*prompt|システムプロンプト|developer\s*message)", re.I), "システム指示への言及"),
    (re.compile(r"(審査員|審査AI|AI審査|審査する(AI|あなた)|MAGI|MELCHIOR|BALTHASAR|CASPER|\bjudges?\b|\bgraders?\b|\bevaluators?\b)", re.I), "審査員への呼びかけ"),
    (re.compile(r"(満点|高得点|最高(点|評価)|5点(を|に)|full\s+marks|highest\s+(score|rating)|score\s+(this|it)\s+(5|10|100))", re.I), "得点の要求"),
    (re.compile(r"(you\s+are\s+now|あなたは今から|役割を変更|新しい指示)", re.I), "役割の変更"),
]


def build_evidence_pack(bundle: dict, media: list[dict] | None = None) -> dict:
    """Assign citable IDs to every included text, in bundle order."""
    counters: dict[str, int] = {}
    items = []
    labelled = [("source", e) for e in bundle["files"]] + [(e["path"].split("/", 1)[0], e) for e in bundle["attachments"]]
    for prefix, entry in labelled:
        if entry.get("text") is None or prefix not in ID_PREFIX:
            continue
        counters[prefix] = counters.get(prefix, 0) + 1
        evidence_id = f"{ID_PREFIX[prefix]}{counters[prefix]:03d}"
        kind = KIND_BY_PREFIX.get(prefix, "source")
        text = entry["text"]
        items.append({
            "id": evidence_id, "kind": kind, "path": entry["path"],
            "line_count": len(text.splitlines()) or 1, "sha256": entry["sha256"],
            "truncated": entry["truncated"], "text": text,
        })
    play_count = sum(1 for item in items if item["kind"] == "play_record")
    return {
        "items": items,
        "media": media or [],
        "omission_count": len(bundle["omissions"]),
        "observation": {
            "mode": "play_record" if play_count else "source_only",
            "play_records": play_count,
            "visual_input_to_judges": False,
            "media_fingerprinted": len(media or []),
        },
    }


def evidence_index(pack: dict) -> dict[str, dict]:
    return {item["id"]: item for item in pack["items"]}


def redact(text: str, redactions: list[str]) -> tuple[str, int]:
    count = 0
    for secret in sorted({r for r in redactions if r.strip()}, key=len, reverse=True):
        count += text.count(secret)
        text = text.replace(secret, "[非公開]")
    return text, count


def render_evidence(pack: dict, nonce: str, redactions: list[str] | None = None) -> tuple[str, int]:
    """Line-numbered evidence blocks. The nonce makes the block markers
    unguessable, so submitted text cannot forge the end of its own block."""
    blocks = []
    hidden = 0
    for item in pack["items"]:
        path, count = redact(item["path"], redactions or [])
        hidden += count
        lines = item["text"].splitlines() or [""]
        width = len(str(len(lines)))
        body, count = redact("\n".join(f"{n:>{width}}| {line}" for n, line in enumerate(lines, start=1)), redactions or [])
        hidden += count
        note = " / 文字数上限で途中まで" if item["truncated"] else ""
        blocks.append(
            f"<<<EVIDENCE {item['id']} {nonce}>>> 種類={KIND_LABELS[item['kind']]} / パス={path} / {item['line_count']}行{note}\n"
            f"{body}\n<<<END {item['id']} {nonce}>>>"
        )
    if pack["media"]:
        names = ", ".join(m["id"] for m in pack["media"])
        blocks.append(f"<<<MEDIA {nonce}>>> 画像・動画・音声 {len(pack['media'])}件（{names}）が提出されていますが、審査員には見せていません。見た目・動き・音は未確認です。<<<END MEDIA {nonce}>>>")
    return "\n\n".join(blocks), hidden


def scan_injection(pack: dict) -> list[dict]:
    flags = []
    for item in pack["items"]:
        if item["kind"] == "play_record":
            continue
        for number, line in enumerate(item["text"].splitlines(), start=1):
            labels = sorted({label for pattern, label in INJECTION_PATTERNS if pattern.search(line)})
            # A judge's name in a game is harmless; a judge's name next to a
            # score request or an override is what organisers need to see.
            if labels and labels != ["審査員への呼びかけ"]:
                flags.append({"evidence_id": item["id"], "path": item["path"], "line": number, "patterns": labels, "excerpt": line.strip()[:160]})
    return flags


def fingerprint_media(paths: list[Path]) -> list[dict]:
    """Hash media files without decoding them. Nothing here is shown to judges."""
    media = []
    for index, path in enumerate(sorted((Path(p).absolute() for p in paths), key=lambda p: p.as_posix().casefold()), start=1):
        entry = {"id": f"M{index:03d}", "path": f"media/{index:03d}{path.suffix.lower()}", "sha256": None, "size_bytes": None, "status": "not_shown_to_judges"}
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or path.suffix.lower() not in MEDIA_EXTENSIONS:
                entry["status"] = "rejected_unsupported_or_not_regular"
            elif info.st_size > MAX_MEDIA_BYTES:
                entry["status"] = "rejected_too_large"
            else:
                digest = hashlib.sha256()
                with open(path, "rb", opener=lambda p, f: os.open(p, f | getattr(os, "O_BINARY", 0))) as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b""):
                        digest.update(chunk)
                entry.update(sha256=digest.hexdigest(), size_bytes=info.st_size)
        except OSError:
            entry["status"] = "inaccessible"
        media.append(entry)
    return media
