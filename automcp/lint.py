"""L0 정적 검증: IR이 컴파일 가능한지, 근거가 실재하는지, 정책을 지키는지 확인한다.

LLM(해석 에이전트)이 작성한 IR의 환각·정책 위반을 실행 전에 걸러 내는 1차 방어선이다.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import correlate, sqlcheck
from .ir import FLOW_PARAM_RE as FLOW_PARAM
from .ir import Spec, schema_errors, statement_params

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"


@dataclass
class Finding:
    level: str
    tool: str
    message: str

    def __str__(self):
        return f"[{self.level}] {self.tool}: {self.message}"


def _check_source_evidence(spec, tool, out):
    root = spec.source_root
    if not root:
        out.append(Finding(WARN, tool["name"], "system.source_root 미지정 — 소스 근거를 확인하지 못함"))
        return
    for ref in tool["evidence"]["source"]:
        file, line = ref.rsplit(":", 1)
        path = root / file
        if not path.is_file():
            out.append(Finding(ERROR, tool["name"], f"근거 파일 없음: {file}"))
        elif int(line) > len(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            out.append(Finding(ERROR, tool["name"], f"근거 줄 번호가 파일 길이를 넘음: {ref}"))


def _check_capture_evidence(spec, tool, traces, out):
    caps = tool["evidence"].get("capture", [])
    if not caps:
        out.append(Finding(WARN, tool["name"], "캡처 근거 없음 — 정적 분석만으로 설계됨(시연 경로 미검증)"))
        return
    if traces is None:
        out.append(Finding(WARN, tool["name"], "system.capture 미지정 — 캡처 근거를 확인하지 못함"))
        return
    for c in caps:
        if c["trace"] not in traces:
            out.append(Finding(ERROR, tool["name"], f"캡처에 없는 trace: {c['trace']} ({c['step']})"))


def _check_sql(spec, tool, mappers, out):
    b, name = tool["binding"], tool["name"]
    used = statement_params(b["statement"])
    declared = set(tool["input"])
    if set(used) != declared:
        out.append(Finding(ERROR, name, f"입력 파라미터 불일치 — SQL {sorted(set(used))} / input {sorted(declared)}"))
    dup = [p for p, n in Counter(used).items() if n > 1]
    if dup and spec.db_type != "postgres":
        out.append(Finding(ERROR, name, f"{spec.db_type}는 위치 파라미터 재사용 불가: {dup}"))

    try:
        facts = sqlcheck.analyze(b["statement"], spec.db_type)
    except Exception as e:  # sqlglot 파싱 실패
        out.append(Finding(ERROR, name, f"SQL 파싱 실패({spec.db_type}) — 수동 검토 필요: {str(e).splitlines()[0]}"))
        return
    if facts.statements != 1:
        out.append(Finding(ERROR, name, f"단일 문장만 허용 (현재 {facts.statements}개)"))
    if tool["side_effect"] == "read" and not facts.is_select_only:
        out.append(Finding(ERROR, name, "read tool인데 SELECT 외 문장이 포함됨"))
    if tool["side_effect"] != "read" and not spec.data.get("policies", {}).get("allow_write"):
        out.append(Finding(ERROR, name, "쓰기 tool이지만 policies.allow_write=false"))
    if facts.has_star:
        out.append(Finding(ERROR, name, "SELECT * 금지 — 필요한 컬럼만 명시"))
    for hit in sqlcheck.excluded_hits(facts, spec.excluded_columns):
        out.append(Finding(ERROR, name, f"정책 제외 컬럼 참조: {hit}"))
    if tool["side_effect"] == "read" and not facts.has_limit:
        out.append(Finding(WARN, name, f"행 수 제한(LIMIT/FETCH) 없음 — 결과가 큰 경우 max_rows={spec.max_rows} 권장"))

    if mappers is not None:
        known = {m["id"] for m in mappers} | {m["id"].rsplit(".", 2)[-2] + "." + m["id"].rsplit(".", 1)[-1] for m in mappers}
        for ref in b.get("reuse", []):
            if ref not in known:
                out.append(Finding(ERROR, name, f"소스에 없는 매퍼 statement: {ref}"))


def _check_http_flow(spec, tool, out):
    b, name = tool["binding"], tool["name"]
    if "http" not in spec.data["system"]:
        out.append(Finding(ERROR, name, "http-flow 바인딩에는 system.http.base_url 필요"))
    if tool["side_effect"] != "read" and not spec.data.get("policies", {}).get("allow_write"):
        out.append(Finding(ERROR, name, "쓰기 tool이지만 policies.allow_write=false"))
    if tool["side_effect"] != "read" and not b.get("idempotency"):
        out.append(Finding(WARN, name, "쓰기 tool에 중복 실행 방지(idempotency) 전략이 없음"))
    used = set()
    for s in b["steps"] + [b.get("session", {}).get("login") or {"path": "/"}]:
        if not s["path"].startswith("/"):
            out.append(Finding(ERROR, name, f"step 경로는 '/'로 시작해야 함: {s['path']}"))
        form = s.get("form")
        texts = [s["path"]] + ([f"{k}={v}" for k, v in form.items()] if isinstance(form, dict) else [])
        used |= {m for t in texts for m in FLOW_PARAM.findall(t)}
    declared = set(tool["input"]) - {"request_id"}
    if used != declared:
        out.append(Finding(ERROR, name, f"입력 파라미터 불일치 — 흐름 {sorted(used)} / input {sorted(declared)}"))
    if tool["side_effect"] != "read" and "request_id" not in tool["input"]:
        out.append(Finding(WARN, name, "쓰기 tool에 request_id 입력이 없어 재시도 시 중복 실행될 수 있음"))


def lint(spec: Spec):
    errors = schema_errors(spec.data)
    if errors:
        return [Finding(ERROR, "(schema)", e) for e in errors]

    out = []
    names = Counter(t["name"] for t in spec.tools)
    out += [Finding(ERROR, n, "tool 이름 중복") for n, c in names.items() if c > 1]

    traces = None
    if spec.capture_path and spec.capture_path.exists():
        traces = {e["trace_id"] for e in json.loads(spec.capture_path.read_text(encoding="utf-8"))}
    mappers = correlate.index_mappers(spec.source_root) if spec.source_root and spec.source_root.exists() else None

    for tool in spec.tools:
        _check_source_evidence(spec, tool, out)
        _check_capture_evidence(spec, tool, traces, out)
        if tool["binding"]["kind"] == "sql":
            _check_sql(spec, tool, mappers, out)
        else:
            _check_http_flow(spec, tool, out)
        if not tool.get("verify"):
            out.append(Finding(WARN, tool["name"], "verify 항목 없음 — 자동 검증 불가"))
        if tool["review"]["status"] != "approved":
            out.append(Finding(INFO, tool["name"], f"검토 상태: {tool['review']['status']} (승인 전에는 컴파일 제외)"))
    return out


def has_errors(findings):
    return any(f.level == ERROR for f in findings)
