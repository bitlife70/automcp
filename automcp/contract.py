"""IR → 운영자 검토용 인터페이스 계약서(단일 HTML).

운영자는 코드를 읽지 않는다. 이 문서로 tool별 목적·접근 데이터·원본과의 차이·보호 장치를 보고 승인 여부를 정한다.
"""

import html
from datetime import datetime
from pathlib import Path

from . import sqlcheck
from .ir import Spec

SIDE_EFFECT = {"read": ("조회", "read"), "write": ("쓰기", "write"), "destructive": ("삭제·취소", "destructive")}
STATUS = {"pending": "검토 대기", "approved": "승인", "rejected": "반려"}

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6; --card:#fafafa; --read:#1f6feb; --write:#c2410c;
        --ok:#15803d; --warn:#b45309; --code:#f3f3f5; }
@media (prefers-color-scheme: dark) { :root { --bg:#111214; --fg:#e8e8ea; --muted:#9a9aa2; --line:#2a2b30; --card:#18191c;
        --read:#58a6ff; --write:#fb923c; --ok:#4ade80; --warn:#fbbf24; --code:#202126; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.6 -apple-system,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",sans-serif }
main { max-width:960px; margin:0 auto; padding:32px 16px 64px }
h1 { font-size:26px; margin:0 0 4px } h2 { font-size:19px; margin:36px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line) }
h3 { font-size:17px; margin:0 } .muted { color:var(--muted) } code, pre { background:var(--code); border-radius:6px; font:13px/1.5 Consolas,monospace }
code { padding:1px 5px } pre { padding:12px; overflow-x:auto; white-space:pre-wrap }
table { width:100%; border-collapse:collapse; margin:8px 0 } th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top }
th { font-weight:600; color:var(--muted); font-size:13px; width:28% }
.summary { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0 } .stat { border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:120px }
.stat b { display:block; font-size:22px } .card { border:1px solid var(--line); background:var(--card); border-radius:12px; padding:18px; margin:16px 0 }
.head { display:flex; gap:10px; align-items:center; flex-wrap:wrap } .badge { font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px; border:1px solid }
.read { color:var(--read) } .write, .destructive { color:var(--write) } .approved { color:var(--ok) } .pending { color:var(--warn) } .rejected { color:var(--write) }
ul { margin:4px 0; padding-left:20px } details summary { cursor:pointer; color:var(--muted); font-size:13px }
.sign { display:flex; gap:24px; flex-wrap:wrap; margin-top:12px; padding-top:12px; border-top:1px dashed var(--line); font-size:14px }
.q { border-left:3px solid var(--warn); padding:6px 12px; margin:10px 0 } .answer { border-bottom:1px solid var(--line); min-height:28px; margin-top:6px }
@media print { .card { break-inside:avoid } details { display:block } details > * { display:block } }
"""


def esc(v):
    return html.escape(str(v))


def _list(items):
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else '<span class="muted">없음</span>'


def _tables(spec, tool):
    b = tool["binding"]
    if b["kind"] != "sql":
        return "레거시 화면 흐름: " + " → ".join(f"<code>{esc(s['method'])} {esc(s['path'])}</code>" for s in b["steps"])
    try:
        facts = sqlcheck.analyze(b["statement"], spec.db_type)
        return ", ".join(f"<code>{esc(t)}</code>" for t in sorted(facts.tables)) + " <span class='muted'>(조회 전용)</span>" \
            if tool["side_effect"] == "read" else ", ".join(sorted(facts.tables))
    except Exception:
        return '<span class="muted">SQL 분석 불가 — 원문 참고</span>'


def _protections(spec, tool):
    b, items = tool["binding"], []
    items += [f"원본 검증 재현: {g}" for g in b.get("guards", [])]
    items += [f"입력 가공(원본 로직 재현): {t}" for t in b.get("transforms", [])]
    for col, mapping in b.get("code_mapping", {}).items():
        items.append(f"코드값 의미 변환 {col}: " + ", ".join(f"{k}→{v}" for k, v in mapping.items()))
    if b["kind"] == "sql":
        items.append("파라미터 바인딩(SQL 인젝션 차단), 최소권한 DB 계정으로 실행")
        if spec.excluded_columns:
            items.append("반환 금지 컬럼: " + ", ".join(spec.excluded_columns))
    else:
        if b.get("idempotency"):
            items.append(f"중복 실행 방지: {b['idempotency']}")
        if any(s.get("form") == "@prefilled" for s in b["steps"]):
            items.append("화면에 미리 채워진 값(결제수단 등)을 그대로 제출 — 에이전트가 입력하지 않음")
        if b.get("session", {}).get("login"):
            items.append("로그인 자격증명은 런타임 비밀값으로 주입 — 에이전트에게 노출되지 않음")
    return _list(items)


def _tool_card(spec, tool):
    label, cls = SIDE_EFFECT[tool["side_effect"]]
    status = tool["review"]["status"]
    inputs = "".join(f"<tr><td><code>{esc(n)}</code></td><td>{esc(p['type'])}</td><td>{esc(p['description'])}</td></tr>"
                     for n, p in tool["input"].items())
    ev = tool["evidence"]
    capture = [f"시연 단계 {c['step']}" + (f" (실제 값 {c['observed_bind']})" if c.get("observed_bind") else "")
               for c in ev.get("capture", [])]
    checks = []
    if tool.get("verify", {}).get("golden"):
        g = tool["verify"]["golden"]
        checks.append(f"시연 화면과 결과 일치: {g['step']} {g['args']}")
    checks += [c["name"] for c in tool.get("verify", {}).get("cases", [])]
    b = tool["binding"]
    impl = (f"<pre>{esc(b['statement'].strip())}</pre>" if b["kind"] == "sql"
            else "<pre>" + esc("\n".join(f"{s.get('name', '')}: {s['method']} {s['path']}"
                                         + (f"  form={s['form']}" if s.get("form") else "") for s in b["steps"])) + "</pre>")
    rv = tool["review"]
    signed = f"{STATUS[status]} — {esc(rv.get('by', ''))} {esc(rv.get('at', ''))} {esc(rv.get('comment', ''))}" \
        if status != "pending" else "☐ 승인 &nbsp; ☐ 반려 &nbsp; 의견: ______________________"
    return f"""
<section class="card" id="{esc(tool['name'])}">
  <div class="head"><h3>{esc(tool['name'])}</h3>
    <span class="badge {cls}">{label}</span><span class="badge {status}">{STATUS[status]}</span>
    <span class="muted">{esc(tool['use_case'])}</span></div>
  <p>{esc(tool['description'])}</p>
  <table>
    <tr><th>입력</th><td><table>{inputs}</table></td></tr>
    <tr><th>반환</th><td>{', '.join(f'<code>{esc(o)}</code>' for o in tool.get('output', [])) or '-'}</td></tr>
    <tr><th>접근 데이터</th><td>{_tables(spec, tool)}</td></tr>
    <tr><th>원본과 다른 점</th><td>{_list(tool.get('deviations', []))}</td></tr>
    <tr><th>보호 장치</th><td>{_protections(spec, tool)}</td></tr>
    <tr><th>근거</th><td>{_list(capture + ev['source'])}</td></tr>
    <tr><th>자동 검증 항목</th><td>{_list(checks)}</td></tr>
  </table>
  <details><summary>구현 상세 (개발자용)</summary>{impl}</details>
  <div class="sign"><span><b>검토 결과:</b> {signed}</span></div>
</section>"""


def render(spec: Spec, out):
    d = spec.data
    tools = spec.tools
    n_write = sum(t["side_effect"] != "read" for t in tools)
    n_pending = sum(t["review"]["status"] == "pending" for t in tools)
    pol = d.get("policies", {})
    questions = "".join(
        f'<div class="q"><b>{esc(q["id"])}</b> <span class="muted">→ {esc(q["to"])}</span><br>{esc(q["text"])}'
        f'<div class="answer">{esc(q.get("answer", ""))}</div></div>'
        for q in d.get("review", {}).get("questions", []))
    toc = "".join(f'<li><a href="#{esc(t["name"])}">{esc(t["name"])}</a> — {esc(t["use_case"])}</li>' for t in tools)
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(d['system']['name'])} 인터페이스 계약서</title>
<style>{CSS}</style></head><body><main>
<h1>{esc(d['system']['name'])} — AI 에이전트 인터페이스 계약서</h1>
<p class="muted">에이전트 <b>{esc(d['agent']['name'])}</b> · 생성 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 원본 {esc(spec.path.name)}</p>
<p>{esc(d['agent']['persona'])}<br><span class="muted">권한 주체: {esc(d['agent']['acts_as'])}</span></p>
<div class="summary">
  <div class="stat"><b>{len(tools)}</b>tool</div><div class="stat"><b>{len(tools) - n_write}</b>조회</div>
  <div class="stat"><b>{n_write}</b>쓰기</div><div class="stat"><b>{n_pending}</b>검토 대기</div>
</div>
<h2>검토 방법</h2>
<p>각 tool이 <b>무엇을 하는지, 어떤 데이터에 접근하는지, 원본 시스템과 무엇이 다른지</b>를 확인하고 승인 또는 반려해 주세요.
승인된 tool만 배포됩니다. 아래 질문에 대한 답변도 함께 부탁드립니다.</p>
<h2>정책</h2>
<table>
  <tr><th>에이전트에 절대 반환하지 않는 데이터</th><td>{_list(pol.get('excluded_columns', []))}</td></tr>
  <tr><th>반환하지만 감사 로그 대상인 개인정보</th><td>{_list(pol.get('pii_output', []))}</td></tr>
  <tr><th>쓰기 작업 허용</th><td>{'허용' if pol.get('allow_write') else '불허'}</td></tr>
</table>
<h2>확인이 필요한 질문</h2>{questions or '<p class="muted">없음</p>'}
<h2>tool 목록</h2><ol>{toc}</ol>
{''.join(_tool_card(spec, t) for t in tools)}
</main></body></html>"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(doc, encoding="utf-8")
