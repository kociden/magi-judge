"""Self-contained local displays and exports; no submitted HTML is executed.

The look borrows the three-panel deliberation screen of the source anime
(BALTHASAR above, CASPER left, MELCHIOR right) as an event homage. Nothing here
loads external resources; fonts fall back to what Windows ships.
"""
from __future__ import annotations

import csv
from html import escape
import json
from pathlib import Path

from .judging import STATUS_LABELS, VOTE_LABELS
from .rubric import PERSONAS, judge_names


def e(value: object) -> str:
    return escape(str(value), quote=True)


def _points(bounds: dict) -> str:
    return f"{bounds['total']:g}" if bounds["total"] is not None else f"{bounds['lower']:g}〜{bounds['upper']:g}"


# Panel geometry in a 1000x600 box. Each panel leans its chamfer toward the core.
PANELS = {
    "claude": {"points": "330,30 670,30 670,190 612,248 388,248 330,190", "cx": 500, "cy": 118},
    "grok": {"points": "70,322 352,322 420,390 420,570 70,570", "cx": 238, "cy": 438},
    "codex": {"points": "648,322 930,322 930,570 580,570 580,390", "cx": 762, "cy": 438},
}
PANEL_WORD = {"approve": "承認", "reject": "否決", "abstain": "保留", "fault": "障害", "pending": "審議中", "idle": ""}
PANEL_CLASS = {"approve": "approve", "reject": "deny", "abstain": "hold", "fault": "fault", "pending": "pending", "idle": "idle"}
VERDICT_WORD = {"APPROVED": "可決", "REJECTED": "否決", "HOLD": "保留"}

STYLE = """
:root{--void:#000;--signal:#ff8a1c;--signal-dim:#6b3608;--approve:#4ff2c8;--deny:#ff2a2a;--hold:#ffd23f;--fault:#8a8f99;--paper:#f4f1ea;
--mincho:"HGP明朝E","HG明朝E","HGS明朝E","Yu Mincho","YuMincho","Hiragino Mincho ProN","Noto Serif JP",serif;
--readout:"Bahnschrift","DIN Alternate","Arial Narrow","Yu Gothic UI",sans-serif;color-scheme:dark}
*{box-sizing:border-box}html{background:var(--void)}
body{margin:0;background:var(--void);color:var(--signal);font-family:var(--readout);font-stretch:condensed;line-height:1.6}
.mincho{font-family:var(--mincho);font-weight:900}
svg.triad{display:block;width:100%;height:auto;overflow:visible}
.triad .bus{stroke:var(--signal-dim);stroke-width:26;stroke-linecap:butt}
.triad .core{fill:var(--signal);font-family:var(--mincho);font-weight:900;font-size:46px;letter-spacing:.08em}
.triad polygon{stroke:var(--signal);stroke-width:4;fill:transparent;transition:fill .18s steps(2)}
.triad .name{font-family:var(--mincho);font-weight:900;font-size:44px;fill:var(--signal)}
.triad .word{font-family:var(--mincho);font-weight:900;font-size:64px;fill:var(--signal)}
.triad .pts{font-family:var(--readout);font-size:26px;fill:var(--signal);letter-spacing:.04em}
.triad g.approve polygon{fill:var(--approve);stroke:var(--approve)}.triad g.deny polygon{fill:var(--deny);stroke:var(--deny)}
.triad g.hold polygon{fill:var(--hold);stroke:var(--hold)}.triad g.fault polygon{fill:url(#hatch);stroke:var(--fault)}
.triad g.approve text,.triad g.deny text,.triad g.hold text{fill:#000}.triad g.fault text{fill:#fff}
.triad g.pending polygon{animation:blink .5s steps(1) infinite}
@keyframes blink{50%{fill:rgba(255,138,28,.42)}}
.box{border:3px double var(--signal);padding:10px 16px;min-width:0}
.box>h3{margin:0 0 6px;font-family:var(--mincho);font-weight:900;font-size:22px;letter-spacing:.3em;color:var(--signal)}
.verdict-word{font-family:var(--mincho);font-weight:900;font-size:clamp(44px,7vw,96px);line-height:1;letter-spacing:.08em;padding:6px 14px;display:inline-block;border:4px solid currentColor}
.v-APPROVED{color:var(--approve)}.v-REJECTED{color:var(--deny)}.v-HOLD{color:var(--hold)}.v-system{color:var(--fault)}
a{color:var(--signal)}:focus-visible{outline:3px solid var(--approve);outline-offset:3px}
@media (prefers-reduced-motion:reduce){.triad g.pending polygon{animation:none;fill:rgba(255,138,28,.25)}*{transition:none!important}}
"""

REPORT_STYLE = """
body{padding:28px clamp(16px,4vw,48px) 48px;max-width:1440px;margin:0 auto}
.masthead{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;border-bottom:2px solid var(--signal);padding-bottom:8px}
.masthead h1{margin:0;font-size:clamp(30px,5vw,56px);line-height:1;color:var(--signal)}
.masthead p{margin:0;text-align:right;font-size:14px}
.sim{color:var(--hold)}
.stage .verdict-word{font-size:clamp(40px,4.6vw,72px);max-width:100%}
.stage{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr) minmax(0,1fr);gap:20px;align-items:start;margin:24px 0}
.stage .box p{margin:4px 0;font-size:15px;color:var(--paper)}
.title{font-family:var(--mincho);font-weight:900;font-size:clamp(22px,2.6vw,32px);color:var(--paper);line-height:1.25;margin:6px 0}
.reason{font-size:14px;color:var(--paper)}
.seats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:8px}
.seat{border-top:6px solid var(--signal);padding-top:12px;min-width:0}
.seat.approve{border-color:var(--approve)}.seat.deny{border-color:var(--deny)}.seat.hold{border-color:var(--hold)}.seat.fault{border-color:var(--fault)}
.seat h2{margin:0;font-family:var(--mincho);font-weight:900;font-size:28px;line-height:1.2}
.seat .role{font-size:13px;color:var(--fault)}
.big{font-size:44px;line-height:1.1;color:var(--paper);font-weight:600}.big small{font-size:16px;color:var(--signal)}
.note{font-size:13px;color:#d9c6a6}
table{width:100%;border-collapse:collapse;font-size:15px;margin:10px 0}
th{text-align:left;font-weight:400;padding:5px 6px 5px 0;color:var(--paper)}td{padding:5px 0 5px 6px;text-align:right}
tr{border-top:1px solid var(--signal-dim)}
.st{font-size:12px;padding:0 6px;border:1px solid;margin-right:6px}.st.observed{color:var(--approve)}.st.inferred{color:var(--hold)}.st.not_observed{color:var(--fault);border-style:dashed}
.summary{color:var(--paper);font-family:var(--mincho);font-weight:400;font-size:15px;line-height:1.9}
details{margin-top:10px;font-size:14px;color:var(--paper)}summary{cursor:pointer;color:var(--signal)}li{margin:6px 0;overflow-wrap:anywhere}
code{font-family:var(--readout);color:var(--approve)}.warn{color:var(--hold)}
.alert{border:3px solid var(--deny);padding:12px 18px;margin:24px 0;color:var(--paper)}.alert b{color:var(--deny)}
.ranking td,.ranking th{font-size:16px}.ranking .won th{color:var(--approve)}
footer{margin-top:36px;border-top:1px solid var(--signal-dim);padding-top:10px;font-size:12px;color:#a88a66}
@media(max-width:900px){.stage{grid-template-columns:1fr}.seats{grid-template-columns:1fr}.stage .triad-wrap{order:-1}}
"""


def triad_svg(states: dict[str, str], points: dict[str, str] | None = None, svg_id: str | None = None,
              names: dict[str, str] | None = None) -> str:
    """The three-panel MAGI display. states: provider -> approve/reject/abstain/fault/pending/idle."""
    id_attr = f" id='{svg_id}'" if svg_id else ""
    groups = []
    for provider, geo in PANELS.items():
        state = states.get(provider, "idle")
        name = (names or {}).get(provider) or PERSONAS[provider]["role"]
        # Compress only long names; short ones would be stretched by textLength.
        squeeze = " textLength='270' lengthAdjust='spacingAndGlyphs'" if len(name) > 10 else ""
        pts = (points or {}).get(provider, "")
        groups.append(
            f"<g class='p-{provider} {PANEL_CLASS[state]}'><polygon points='{geo['points']}'/>"
            f"<text class='name' x='{geo['cx']}' y='{geo['cy'] - 22}' text-anchor='middle'{squeeze}>{e(name)}</text>"
            f"<text class='word' x='{geo['cx']}' y='{geo['cy'] + 52}' text-anchor='middle'>{e(PANEL_WORD[state])}</text>"
            f"<text class='pts' x='{geo['cx']}' y='{geo['cy'] + 96}' text-anchor='middle'>{e(pts)}</text></g>"
        )
    return (
        f"<svg class='triad'{id_attr} viewBox='0 0 1000 600' role='img' aria-label='MAGI 3基の判定'>"
        "<defs><pattern id='hatch' width='16' height='16' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
        "<rect width='16' height='16' fill='#2a2c30'/><rect width='6' height='16' fill='#8a8f99'/></pattern></defs>"
        "<line class='bus' x1='372' y1='230' x2='392' y2='362'/><line class='bus' x1='628' y1='230' x2='608' y2='362'/>"
        "<line class='bus' x1='420' y1='482' x2='580' y2='482'/>"
        "<text class='core' x='500' y='318' text-anchor='middle'>MAGI</text>"
        + "".join(groups) + "</svg>"
    )


def _panel_state(item: dict) -> str:
    return item["vote"] if item.get("status") == "ok" else "fault"


def _verdict_class(aggregate: dict) -> str:
    return "v-system" if aggregate.get("hold_kind") == "system" else f"v-{aggregate['state']}"


def _score_text(item: dict) -> str:
    if item["score"] is None:
        return "—"
    return f"{item['score']:g}" + (f" ±{item['spread'] / 2:g}" if item["spread"] else "")


def _seat_text(entry: dict) -> str:
    if entry["seat_score"] is not None:
        return f"{entry['seat_score']:g}"
    return f"{entry['seat_range'][0]:g}〜{entry['seat_range'][1]:g}" if entry["seat_range"] else "—"


def _seat(provider: str, item: dict, rubric: dict, name: str) -> str:
    persona = PERSONAS[provider]
    state = PANEL_CLASS[_panel_state(item)]
    model = next((s.get("model_used") for s in item.get("samples", []) if s.get("model_used")), None) or "モデル名は不明"
    head = f"<h2>{e(name)}</h2><div class='role'>{e(persona['role'])}の目線 ／ {e(model)} ／ {e(persona['view'])}</div>"
    if item["status"] != "ok":
        label = "未実行" if item["status"] == "skipped" else "障害"
        return f"<section class='seat {state}'>{head}<p class='big'>{label}</p><p class='note'>{e(item.get('error') or '')}<br>票には数えません。</p></section>"
    d = item["decision"]
    rows = "".join(
        f"<tr><th>{e(c['label'])}</th><td><span class='st {e(item['criteria'][c['id']]['status'])}'>{e(STATUS_LABELS[item['criteria'][c['id']]['status']])}</span>"
        f"{_score_text(item['criteria'][c['id']])}</td></tr>"
        for c in rubric["criteria"]
    )
    cites = "".join(
        f"<li><b>{e(c['label'])}</b> {e(d['criteria'][c['id']]['rationale'])}"
        + "".join(f"<br><code>{e(v['evidence_id'])}{':' + e(v['line_start']) if v['line_start'] else ''}{'-' + e(v['line_end']) if v['line_end'] and v['line_end'] != v['line_start'] else ''}</code> {e(v['observation'])}" for v in d["criteria"][c["id"]]["evidence"])
        + (f"<br><i>限界：{e(d['criteria'][c['id']]['limits'])}</i>" if d["criteria"][c["id"]]["limits"].strip() else "") + "</li>"
        for c in rubric["criteria"]
    )
    notes = "".join(f"<li>未確認：{e(u)}</li>" for u in d["uncertainties"])
    notes += "".join(f"<li>ホスト補正：{e(a)}</li>" for s in item["samples"] for a in s.get("host_adjustments", []))
    notes += "".join(f"<li class='warn'>審査員の指摘：<code>{e(f['evidence_id'])}</code> {e(f['description'])}</li>" for f in d["integrity_flags"])
    feedback = "".join(f"<li>良い点：{e(s)}</li>" for s in d["feedback"]["strengths"]) + "".join(f"<li>提案：{e(s)}</li>" for s in d["feedback"]["suggestions"])
    extra = f"{len(item['samples'])}回採点の平均。" if len(item["samples"]) > 1 else ""
    extra += f"試行{item['reused_from_attempt']}の結果を再利用。" if item.get("reused_from_attempt") else ""
    return (
        f"<section class='seat {state}'>{head}<p class='big'>{e(_points(item['persona']))}<small> / 100 本人配点</small></p>"
        f"<p class='note'>{e(item['vote_reason'])}<br>共通配点 {e(_points(item['common']))} ／ 採点済み {e(round(item['common']['coverage'] * 100))}% {e(extra)}</p>"
        f"<table>{rows}</table><p class='summary'>{e(d['summary'])}</p>"
        f"<details><summary>根拠</summary><ul>{cites}</ul></details>"
        f"<details><summary>制作チームへの講評</summary><ul>{feedback}</ul></details>"
        + (f"<details><summary>未確認・補正</summary><ul>{notes}</ul></details>" if notes else "") + "</section>"
    )


def _page(title: str, body: str, *, script: str = "", extra_style: str = "") -> str:
    script_src = "; script-src 'unsafe-inline'" if script else ""
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'{script_src}; base-uri 'none'; form-action 'none'\">"
        f"<title>{e(title)}</title><style>{STYLE}{extra_style}</style></head><body>{body}"
        + (f"<script>{script}</script>" if script else "") + "</body></html>"
    )


def _masthead(result: dict, caption: str) -> str:
    rubric = result["rubric"]
    sim = "<span class='sim'>SIMULATION ／ 架空の判定</span><br>" if result["demo"] else ""
    meta = ("仮の採点基準" if rubric.get("provisional", True) else "確定した採点基準") + f" ／ 推薦の閾値 {rubric['recommendation_threshold']}点"
    if rubric.get("theme"):
        meta += f" ／ テーマ「{rubric['theme']}」"
    return f"<header class='masthead'><h1 class='mincho'>MAGI SYSTEM</h1><p>{sim}{e(caption)}<br>{e(meta)}</p></header>"


FOOTER = ("<footer>3つの独立した視点によるイベント用の審査システム。エヴァンゲリオン公式のシステムではありません。最終決定は運営と人間の審査員が行います。"
          "「観測」は資料で直接確認、「推定」はソースや主張からの推定、「未確認」は判断材料なし（0点ではありません）。</footer>")


def write_report(result: dict, path: Path) -> None:
    if result["kind"] == "comparison":
        path.write_text(_award_page(result), encoding="utf-8")
        return
    rubric, agg = result["rubric"], result["aggregate"]
    items = {r["provider"]: r for r in result["results"]}
    names = judge_names([result])
    states = {p: _panel_state(items[p]) for p in PERSONAS}
    points = {p: _points(items[p]["persona"]) if items[p]["status"] == "ok" else "" for p in PERSONAS}
    obs = "運営のプレイ記録あり" if result["observation"]["mode"] == "play_record" else "プレイ記録なし（面白さ・手触りは推定）"
    seat = agg.get("seat_score")
    word = "障害" if agg.get("hold_kind") == "system" else VERDICT_WORD[agg["state"]]
    stage = (
        "<div class='stage'><section class='box'><h3>提訴</h3>"
        f"<p class='title'>{e(result['title'])}</p><p>審査員への提示名：{e(result['entry_alias'])}</p><p>{e(obs)}</p><p>画像・動画は審査員に未提示</p>"
        f"<p>議案：{e(rubric['motion'])}</p></section>"
        f"<div class='triad-wrap'>{triad_svg(states, points, names=names)}</div>"
        f"<section class='box'><h3>決議</h3><span class='verdict-word {_verdict_class(agg)}'>{e(word)}</span>"
        f"<p class='title'>{e(agg['label'])}</p><p class='reason'>{e(agg['reason'])}</p>"
        f"<p class='reason'>3基の平均点（共通配点）：{e(seat if seat is not None else '未確定')}</p></section></div>"
    )
    alert = ""
    if result["host_integrity_flags"]:
        alert = "<section class='alert'><b>要確認：審査員への指示に見える記述</b><ul>" + "".join(
            f"<li><code>{e(f['evidence_id'])}:{e(f['line'])}</code> {e(f['path'])} — {e('・'.join(f['patterns']))}<br>{e(f['excerpt'])}</li>" for f in result["host_integrity_flags"]
        ) + "</ul><span class='note'>自動検出です。得点には反映していません。</span></section>"
    seats = "<div class='seats'>" + "".join(_seat(p, items[p], rubric, names[p]) for p in PERSONAS) + "</div>"
    scope = ("<details><summary>資料の取得範囲</summary><ul>" + "".join(f"<li>{e(v)}</li>" for v in result.get("limitations", []))
             + "</ul><p>証拠パック：" + "、".join(f"{e(i['id'])}={e(i['path'])}" for i in result["evidence"])
             + f"。省略 {e(result.get('omission_count', 0))} 項目。詳細はbundle.json / evidence.json。</p></details>")
    body = _masthead(result, f"審議記録 ／ {result['entry_alias']}") + stage + alert + seats + scope + FOOTER
    path.write_text(_page(f"MAGI 審議 {result['title']}", body, extra_style=REPORT_STYLE), encoding="utf-8")


def _award_page(result: dict) -> str:
    agg = result["aggregate"]
    names = result["judge_names"]
    winners = set(agg["winners"])
    mode = {"unanimous": "全会一致", "majority": "多数決", "average": "推しが割れたため平均点で決定"}.get(agg["mode"], "授与保留")
    states = {}
    for pick in result["picks"]:
        states[pick["provider"]] = "fault" if pick["kind"] == "system" else "approve" if pick["winner"] and pick["winner"]["entry_id"] in winners else "abstain" if not pick["winner"] else "reject"
    points = {p["provider"]: (p["winner"]["title"][:10] if p["winner"] else "") for p in result["picks"]}
    rows = "".join(
        f"<tr class='{'won' if x['entry_id'] in winners else ''}'><th class='mincho'>{e(x['title'])}</th><td>{e(x['label'])}</td>"
        f"<td>{'・'.join(e(VOTE_LABELS.get(v, '障害') if v else '障害') for v in x['votes'].values())}</td>"
        f"<td>{e(_seat_text(x))}</td></tr>"
        for x in result["entries"]
    )
    picks = "".join(f"<p>{e(names[p['provider']])} の推薦：{e(p['winner']['title'] if p['winner'] else 'なし')}<span class='note'>（{e(p['reason'])}）</span></p>" for p in result["picks"])
    word = "授与" if agg["state"] == "APPROVED" else "保留"
    stage = (
        "<div class='stage'><section class='box'><h3>提訴</h3><p class='title'>MAGI賞</p>"
        "<p>3基がそれぞれ1作品を推し、2基以上が推した作品が受賞。割れた場合は、推された作品のうち3基の平均点が最も高い作品が受賞。</p>"
        f"<p>審議対象 {len(result['entries'])} 作品</p></section>"
        f"<div class='triad-wrap'>{triad_svg(states, points, names=names)}</div>"
        f"<section class='box'><h3>決議</h3><span class='verdict-word v-{e(agg['state'])}'>{word}</span>"
        f"<p class='title'>{e(agg['label'])}</p><p class='reason'>{e(mode)}。{e(agg['reason'])}</p></section></div>"
    )
    table = f"<section><h2 class='mincho'>全作品</h2><table class='ranking'><tr><th>作品</th><td>作品ごとの決議</td><td>{e('・'.join(names.values()))}</td><td>3基の平均点</td></tr>{rows}</table></section>"
    mixed = [f"{PERSONAS[p]['role']}の目線：{'、'.join(m)}" for p, m in result.get("models_used", {}).items() if len(m) > 1]
    warn = ("<section class='alert'><b>要確認：作品によって使われたモデルが違います</b><ul>" + "".join(f"<li>{e(x)}</li>" for x in mixed)
            + "</ul><span class='note'>CLIの既定モデルが途中で変わった可能性があります。本番は --model で固定してください。</span></section>") if mixed else ""
    body = _masthead(result, "MAGI賞 決議記録") + stage + warn + table + f"<section class='box'><h3>各基の推薦</h3>{picks}</section>" + FOOTER
    return _page("MAGI賞 決議", body, extra_style=REPORT_STYLE)


STAGE_STYLE = """
html,body{height:100%;overflow:hidden}body{cursor:none}
.scene{position:fixed;inset:0;display:none;padding:3.2vh 3.2vw}.scene.on{display:flex}
.frame{position:absolute;inset:2vh 1.6vw;border:2px solid var(--signal-dim);pointer-events:none}
.hud{position:absolute;left:3.2vw;right:3.2vw;bottom:3vh;display:flex;justify-content:space-between;font-size:1.6vh;color:var(--signal-dim)}
.opening{flex-direction:column;align-items:center;justify-content:center;text-align:center}
.opening .triad-holder{width:78vh}
.opening h1{margin:2vh 0 0;font-family:var(--mincho);font-weight:900;font-size:9vh;letter-spacing:.12em;line-height:1;color:var(--signal)}
.opening p{font-size:2.2vh;color:var(--paper);margin:1vh 0}
.deliberation{display:grid;grid-template-columns:19vw 1fr 19vw;gap:1.6vw;width:100%;align-items:center}
.deliberation .box p{margin:.6vh 0;font-size:2.4vh;color:var(--paper)}
.deliberation .box>h3{font-size:3vh}
.deliberation .title{font-family:var(--mincho);font-weight:900;font-size:5vh;line-height:1.2;color:var(--paper);margin:1vh 0}
.deliberation .triad{max-height:86vh}
.triad .word.pick{font-size:46px}
.triad g.pick polygon{fill:var(--signal);stroke:var(--signal)}.triad g.pick text{fill:#000}
#verdict{visibility:hidden;font-size:11vh}#verdict.on{visibility:visible;animation:stamp .35s steps(3)}
#verdict-sub{font-family:var(--mincho);font-weight:900;font-size:3.4vh;color:var(--paper);min-height:4vh;white-space:pre-line}
@keyframes stamp{0%{opacity:0;transform:scale(1.6)}100%{opacity:1;transform:scale(1)}}
.card{flex-direction:column;justify-content:center;padding:0 9vw;background:#000}
.card .ep{font-family:var(--mincho);font-weight:900;font-size:6vh;letter-spacing:.3em;color:var(--approve)}
.card .ep.held{color:var(--hold)}
.card h1{margin:2vh 0 0;font-family:var(--mincho);font-weight:900;font-size:15vh;line-height:1.05;color:#fff;transform:scaleX(.78);transform-origin:left;white-space:pre-line;width:128%}
.card .why{margin-top:4vh;font-size:2.6vh;color:var(--paper);max-width:70vw}
.sim{position:fixed;top:2.4vh;right:3.2vw;color:var(--hold);font-size:1.8vh;z-index:3}
.board{flex-direction:column;padding:6vh 6vw 8vh}
.board h2{margin:0 0 2.4vh;font-family:var(--mincho);font-weight:900;font-size:5vh;letter-spacing:.2em;color:var(--signal)}
.board h2 small{display:inline;margin-left:1.4em;font-family:var(--readout);font-weight:400;font-size:2vh;letter-spacing:0;color:var(--paper)}
.rows{display:flex;flex-direction:column;justify-content:center;flex:1;min-height:0;--fs:6.4vh}
.row{display:grid;grid-template-columns:2em minmax(0,1fr) 7em 3.4em;align-items:center;gap:.6em;font-size:var(--fs);border-top:1px solid var(--signal-dim);padding:2.4vh 0}
.row.outside{margin-top:4vh;border-top:2px dashed var(--signal)}
.row .rank{font-family:var(--readout);color:var(--signal)}
.row .name{font-family:var(--mincho);font-weight:900;color:var(--paper);line-height:1.15;min-width:0;overflow-wrap:anywhere}
.row .name em{display:block;font-style:normal;font-family:var(--readout);font-weight:400;font-size:.42em;line-height:1.3;color:var(--signal)}
.row .bar{height:.5em;background:var(--signal-dim);position:relative}.row .bar i{position:absolute;inset:0 auto 0 0;background:var(--signal)}
.row .num{font-family:var(--readout);font-weight:600;color:var(--paper);text-align:right}
.row.won .name,.row.won .num{color:var(--approve)}.row.won .bar i{background:var(--approve)}
.row.partial .bar i{background:repeating-linear-gradient(90deg,var(--signal) 0 6px,transparent 6px 10px)}
@media (prefers-reduced-motion:reduce){#verdict.on{animation:none}}
"""

STAGE_SCRIPT = r"""
const D = JSON.parse(document.getElementById('magi-data').textContent);
const ORDER = ['codex','claude','grok'];
const CLS = {approve:'approve',reject:'deny',abstain:'hold',fault:'fault',pending:'pending',pick:'pick',idle:'idle'};
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = id => document.getElementById(id);
const steps = ['opening', 'ready', ...ORDER.map(p => 'pick:' + p)];
if (D.verdict.split) steps.push('split');
steps.push('verdict', 'title', 'board');
let index = 0, timers = [];

function fit(el, width) {
  el.removeAttribute('textLength'); el.removeAttribute('lengthAdjust');
  if (el.getComputedTextLength && el.getComputedTextLength() > width) {
    el.setAttribute('textLength', width); el.setAttribute('lengthAdjust', 'spacingAndGlyphs');
  }
}
function setPanel(provider, state, word, pts) {
  const g = $('pick-triad').querySelector('.p-' + provider);
  g.setAttribute('class', 'p-' + provider + ' ' + CLS[state]);
  const w = g.querySelector('.word');
  w.setAttribute('class', 'word' + (state === 'pending' ? '' : ' pick'));
  w.textContent = word; fit(w, 290);
  g.querySelector('.pts').textContent = pts || '';
}
function shown(provider) {
  const p = D.picks[provider];
  if (p.state === 'fault') return ['fault', '障害', ''];
  if (p.state === 'abstain') return ['abstain', '棄権', p.reason];
  return ['pick', p.title, p.points];
}
function stamp(word, cls, sub) {
  const v = $('verdict');
  v.className = 'verdict-word'; void v.offsetWidth;
  if (!word) { v.textContent = ''; $('verdict-sub').textContent = ''; return; }
  v.textContent = word; v.className = 'verdict-word ' + cls + ' on';
  $('verdict-sub').textContent = sub;
}
function show(id) { document.querySelectorAll('.scene').forEach(s => s.classList.toggle('on', s.id === id)); }

function render() {
  timers.forEach(clearTimeout); timers = [];
  const step = steps[index];
  $('hud-pos').textContent = (index + 1) + ' / ' + steps.length;
  if (step === 'opening') { show('opening'); return; }
  if (step === 'title') { show('card'); return; }
  if (step === 'board') { show('board'); return; }
  show('pick');
  // Rebuild the board from scratch so going backwards always shows the right state.
  const revealed = step === 'ready' ? 0 : step.startsWith('pick:') ? ORDER.indexOf(step.slice(5)) + 1 : 3;
  ORDER.forEach((p, k) => {
    if (k >= revealed) { setPanel(p, 'pending', '審議中', ''); return; }
    const [state, word, pts] = shown(p);
    if (step === 'split') { setPanel(p, state === 'pick' ? 'abstain' : state, word, pts); return; }
    if (step === 'verdict') { setPanel(p, D.verdict.panels[p], word, pts); return; }
    setPanel(p, state, word, pts);
  });
  if (step === 'split') stamp('決裂', 'v-HOLD', '3基の推しが割れました\n平均点で決定します');
  else if (step === 'verdict') stamp(D.verdict.word, D.verdict.cls, D.verdict.sub);
  else stamp('', '', '');
}
function go(n) { index = Math.max(0, Math.min(steps.length - 1, index + n)); render(); }
document.addEventListener('keydown', ev => {
  if ([' ', 'ArrowRight', 'Enter', 'PageDown'].includes(ev.key)) { ev.preventDefault(); go(1); }
  else if (['ArrowLeft', 'Backspace', 'PageUp'].includes(ev.key)) { ev.preventDefault(); go(-1); }
  else if (ev.key === 'r') render();
  else if (ev.key === 'f') { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {}); }
});
document.addEventListener('click', () => go(1));
(function fill() {
  $('open-count').textContent = '審議対象 ' + D.count + ' 作品' + (D.theme ? ' ／ テーマ「' + D.theme + '」' : '');
  $('card-ep').textContent = D.verdict.held ? '審議保留' : 'MAGI賞';
  $('card-ep').classList.toggle('held', D.verdict.held);
  $('card-title').textContent = D.verdict.winners.join('\n');
  $('card-why').textContent = D.verdict.reason;
  const rows = $('board-rows');
  D.board.forEach(b => {
    const row = document.createElement('div');
    row.className = 'row' + (b.won ? ' won' : '') + (b.seat === null ? ' partial' : '') + (b.outside ? ' outside' : '');
    const rank = document.createElement('span'); rank.className = 'rank'; rank.textContent = b.rank;
    const name = document.createElement('span'); name.className = 'name'; name.textContent = b.title;
    if (b.pickedBy.length) { const tag = document.createElement('em'); tag.textContent = '推し：' + b.pickedBy.join('・'); name.appendChild(tag); }
    const bar = document.createElement('span'); bar.className = 'bar';
    const fill = document.createElement('i'); fill.style.width = Math.max(0, Math.min(100, b.width)) + '%'; bar.appendChild(fill);
    const num = document.createElement('span'); num.className = 'num'; num.textContent = b.label;
    row.append(rank, name, bar, num); rows.appendChild(row);
  });
})();
render();
"""


def write_stage(comparison: dict, runs: list[dict], path: Path) -> None:
    """Projector screen for the announcement. Every entry is judged beforehand;
    on stage each judge reveals its pick, then the MAGI award is decided."""
    award = comparison["aggregate"]
    winners = set(award["winners"])
    names = comparison["judge_names"]
    titles = {r["bundle_digest"]: r["title"] for r in runs}
    picked_by = {}
    for pick in comparison["picks"]:
        if pick["winner"]:
            picked_by.setdefault(pick["winner"]["entry_id"], []).append(names[pick["provider"]])
    board, rank = [], 0
    for position, entry in enumerate(comparison["entries"], start=1):
        if entry["seat_score"] is None or not board or board[-1]["seat"] != entry["seat_score"]:
            rank = position
        seat, span = entry["seat_score"], entry["seat_range"]
        board.append({
            "rank": rank if seat is not None else "—", "title": " ".join(entry["title"].splitlines()), "seat": seat,
            "label": f"{seat:g}" if seat is not None else (f"{span[0]:g}〜" if span else "障害"),
            "width": seat if seat is not None else (span[0] if span else 0),
            "won": entry["entry_id"] in winners, "pickedBy": picked_by.get(entry["entry_id"], []),
        })
    # Only the top three averages are shown (ties at third included). A winner
    # chosen from below them is added after a divider so the result is explained.
    top = [b for b in board if isinstance(b["rank"], int) and b["rank"] <= 3]
    board = top + [{**b, "outside": True} for b in board if b["won"] and b not in top]
    picks, final = {}, {}
    for pick in comparison["picks"]:
        provider = pick["provider"]
        if pick["kind"] == "system":
            picks[provider], final[provider] = {"state": "fault"}, "fault"
        elif not pick["winner"]:
            picks[provider], final[provider] = {"state": "abstain", "reason": pick["reason"][:24]}, "abstain"
        else:
            won = pick["winner"]["entry_id"] in winners
            picks[provider] = {"state": "pick", "title": pick["winner"]["title"].replace("\n", " "), "points": f"{pick['winner']['total']:g} 点"}
            final[provider] = "approve" if won else "reject"
    held = award["state"] != "APPROVED"
    word = "保留" if held else {"unanimous": "全会一致", "majority": "可決", "average": "可決"}[award["mode"]]
    cls = "v-HOLD" if held else "v-APPROVED"
    sub = award["label"] if held else "MAGI賞\n" + "\n".join(titles[w].replace("\n", " ") for w in award["winners"])
    data = {
        "theme": comparison["rubric"].get("theme"), "count": len(runs), "picks": picks, "board": board,
        "verdict": {
            "split": award.get("mode") == "average" and len(award.get("votes", {})) == 3,
            "held": held, "word": word, "cls": cls, "sub": sub, "panels": final, "reason": award["reason"],
            "winners": [titles[w] for w in award["winners"]] or ["該当作品の決定を保留"],
        },
    }
    payload = json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    sim = "<div class='sim'>SIMULATION ／ 架空の判定</div>" if comparison["demo"] else ""
    body = (
        f"{sim}<div class='frame'></div>"
        f"<section class='scene opening' id='opening'><div class='triad-holder'>{triad_svg({p: 'pending' for p in PERSONAS}, names=names)}</div>"
        "<h1>MAGI SYSTEM</h1><p>AI Gamejam Sapporo ／ MAGI賞 審議</p><p id='open-count'></p>"
        "<p class='note'>Space・→で進む ／ ←で戻る ／ Fで全画面 ／ Rでやり直し</p></section>"
        "<section class='scene' id='pick'><div class='deliberation'>"
        "<div class='box'><h3>提訴</h3><p class='title'>MAGI賞</p><p>議案：最も優れた作品を1つ推薦せよ</p>"
        "<p>2基以上が推した作品に授与。割れた場合は、推された作品のうち3基の平均点が最も高い作品に授与。</p></div>"
        f"<div>{triad_svg({p: 'idle' for p in PERSONAS}, svg_id='pick-triad', names=names)}</div>"
        "<div class='box'><h3>決議</h3><span id='verdict' class='verdict-word'></span><p id='verdict-sub'></p></div>"
        "</div></section>"
        "<section class='scene card' id='card'><div class='ep' id='card-ep'></div><h1 id='card-title'></h1><div class='why' id='card-why'></div></section>"
        "<section class='scene board' id='board'><h2>平均点 上位3作品<small>3つのAIの採点（共通配点）の平均。100点満点。MAGI賞は各AIの推しの中から決まります</small></h2><div class='rows' id='board-rows'></div></section>"
        "<div class='hud'><span>MAGI ／ 3基の独立審議。エヴァンゲリオン公式のシステムではありません</span><span id='hud-pos'></span></div>"
        f"<script type='application/json' id='magi-data'>{payload}</script>"
    )
    path.write_text(_page("MAGI賞 審議", body, script=STAGE_SCRIPT, extra_style=STAGE_STYLE), encoding="utf-8")


def write_feedback(result: dict, path: Path) -> None:
    """Team-facing review notes. Scores are included; organisers decide what to share."""
    names = judge_names([result])
    lines = [f"# MAGI 講評：{result['title']}", ""]
    if result["demo"]:
        lines += ["> デモ用の架空の講評です。", ""]
    for provider, persona in PERSONAS.items():
        item = next(r for r in result["results"] if r["provider"] == provider)
        lines.append(f"## {names[provider]}（{persona['role']}の目線）")
        if item["status"] != "ok":
            lines += ["", "（審査を完了できませんでした）", ""]
            continue
        decision = item["decision"]
        lines += ["", decision["summary"], "", "**良かった点**", ""] + [f"- {s}" for s in decision["feedback"]["strengths"]]
        lines += ["", "**次に試すとよさそうなこと**", ""] + [f"- {s}" for s in decision["feedback"]["suggestions"]] + [""]
    lines.append("---")
    lines.append("MAGIはAIによる審査の参考意見です。辛めの基準で採点しています。資料から確認できなかった点は「未確認」として扱っています。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_scores_csv(runs: list[dict], path: Path) -> None:
    """One row per entry for combining MAGI with the human judges' sheet."""
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        header = ["作品", "提示名", "判定", "全会一致", "3基の平均点"]
        for name in judge_names(runs).values():
            header += [f"{name} 票", f"{name} 本人配点", f"{name} 共通配点", f"{name} 採点済み率"]
        writer.writerow(header)
        for run in runs:
            seat = run["aggregate"].get("seat_score")
            row = [run["title"], run["entry_alias"], run["aggregate"]["label"], "○" if run["aggregate"].get("unanimous") else "", "" if seat is None else seat]
            for provider in PERSONAS:
                item = next(r for r in run["results"] if r["provider"] == provider)
                if item["status"] != "ok":
                    row += ["障害", "", "", ""]
                else:
                    row += [VOTE_LABELS[item["vote"]], _points(item["persona"]), _points(item["common"]), item["common"]["coverage"]]
            writer.writerow(row)
