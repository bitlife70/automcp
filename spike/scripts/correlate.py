"""캡처 상관분석기: 시연 트레이스(OTel JSONL)를 소스와 연결해 "엔드포인트 맵"을 만든다.

시연 단계 라벨 → HTTP 요청(경로, 파라미터) → 컨트롤러 메서드(file:line)
                → 실행 SQL(바인딩 값 포함) → MyBatis 매퍼 statement(file#id)

LLM 없이 결정적으로 만드는 부분이며, 이 결과가 IR(mcp-spec) 작성의 근거(evidence)가 된다.

사용: python -I correlate.py <traces.jsonl> <source_root> <out_dir>
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

STATIC_ROUTE = re.compile(r"/\*\*$|\.(css|js|gif|png|jpg|ico|html)$")
# 민감 컬럼을 다루는 SQL의 바인딩 값은 산출물에 남기지 않는다.
# (원본 traces.jsonl도 고객 내부망 밖으로 반출 금지. 다음 단계에서 수집기 redaction으로 이동)
SENSITIVE_SQL = re.compile(r"password|creditcard|exprdate|cardtype|jumin|ssn", re.I)


def attr_value(v):
    """OTLP AnyValue → 파이썬 값 (문자열 배열은 첫 값만)."""
    if "arrayValue" in v:
        vals = v["arrayValue"].get("values", [])
        return attr_value(vals[0]) if vals else None
    if "values" in v:  # 일부 exporter 형식
        vals = v["values"]
        return attr_value(vals[0]) if vals else None
    return next(iter(v.values()), None)


def load_spans(path):
    spans = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for rs in json.loads(line).get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    s["scope"] = ss.get("scope", {}).get("name", "")
                    s["attrs"] = {a["key"]: attr_value(a["value"]) for a in s.get("attributes", [])}
                    spans.append(s)
    return spans


def normalize_sql(sql):
    sql = re.sub(r"#\{[^}]*\}|\$\{[^}]*\}|\?|\$\d+", "?", sql)
    return re.sub(r"\s+", " ", sql).strip().lower()


def index_mappers(src_root):
    """MyBatis 매퍼 XML의 모든 statement를 정규화된 SQL로 색인한다."""
    index = []
    for xml_path in Path(src_root).rglob("*Mapper.xml"):
        root = ET.parse(xml_path).getroot()
        ns = root.get("namespace", "")
        text = xml_path.read_text(encoding="utf-8")
        for el in root:
            if el.tag not in ("select", "insert", "update", "delete"):
                continue
            sid = el.get("id")
            line = next((i + 1 for i, l in enumerate(text.splitlines()) if f'id="{sid}"' in l), 0)
            index.append({
                "id": f"{ns}.{sid}",
                "kind": el.tag,
                "file": xml_path.relative_to(src_root).as_posix(),
                "line": line,
                "sql": normalize_sql("".join(el.itertext())),
            })
    return index


def find_mapper(sql, mappers):
    norm = normalize_sql(sql)
    for m in mappers:
        if m["sql"] == norm:
            return m
    return None


def find_method(src_root, namespace, function):
    """컨트롤러 클래스 소스에서 메서드 선언 위치를 찾는다."""
    rel = Path("src/main/java", *namespace.split(".")).with_suffix(".java")
    path = Path(src_root, rel)
    if not path.exists():
        return None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(rf"\b{re.escape(function)}\s*\(", line) and re.search(r"\b(public|protected|private)\b", line):
            return f"{rel.as_posix()}:{i}"
    return None


def correlate(spans, src_root):
    mappers = index_mappers(src_root)
    by_trace = defaultdict(list)
    for s in spans:
        by_trace[s["traceId"]].append(s)

    entries = []
    for trace_id, tspans in by_trace.items():
        server = next((s for s in tspans if s["kind"] == 2 and "http.request.method" in s["attrs"]), None)
        if not server:
            continue
        a = server["attrs"]
        route = a.get("http.route") or a.get("url.path", "")
        if STATIC_ROUTE.search(route) or STATIC_ROUTE.search(a.get("url.path", "")):
            continue
        ctrl = next((s for s in tspans if "webmvc" in s["scope"] and "code.function" in s["attrs"]), None)
        sqls = []
        for s in sorted((s for s in tspans if s["scope"].endswith("jdbc") and s["attrs"].get("db.statement")),
                        key=lambda s: int(s["startTimeUnixNano"])):
            sa = s["attrs"]
            params = [v for k, v in sorted(
                ((k, v) for k, v in sa.items() if k.startswith("db.query.parameter.")),
                key=lambda kv: int(kv[0].rsplit(".", 1)[-1]))]
            # SELECT는 WHERE 절의 조건 값만 바인딩되므로 WHERE 절만, INSERT/UPDATE는 문장 전체를 검사한다.
            stmt = sa["db.statement"]
            checked = re.split(r"\bwhere\b", stmt, maxsplit=1, flags=re.I)[-1] if sa.get("db.operation") == "SELECT" else stmt
            if SENSITIVE_SQL.search(checked):
                params = ["***"] * len(params)
            m = find_mapper(sa["db.statement"], mappers)
            sqls.append({
                "operation": sa.get("db.operation"),
                "table": sa.get("db.sql.table"),
                "bound_params": params,
                "mapper": m and {"id": m["id"], "evidence": f'{m["file"]}:{m["line"]}'},
                "statement": re.sub(r"\s+", " ", sa["db.statement"]).strip(),
            })
        entries.append({
            "step": a.get("http.request.header.x-automcp-step"),
            "start": int(server["startTimeUnixNano"]),
            "trace_id": trace_id,
            "method": a.get("http.request.method"),
            "route": route,
            "query": a.get("url.query"),
            "request_params": {k.split(".")[-1]: v for k, v in a.items() if k.startswith("servlet.request.parameter.")},
            "status": a.get("http.response.status_code"),
            "controller": ctrl and {
                "method": f'{ctrl["attrs"]["code.namespace"].rsplit(".", 1)[-1]}.{ctrl["attrs"]["code.function"]}',
                "evidence": find_method(src_root, ctrl["attrs"]["code.namespace"], ctrl["attrs"]["code.function"]),
            },
            "sql": sqls,
        })
    entries.sort(key=lambda e: e["start"])
    for e in entries:
        del e["start"]
    return entries


def to_markdown(entries):
    out = ["# 엔드포인트 맵 (캡처 기반)", "",
           "| 단계 | 요청 | 컨트롤러 | SQL (매퍼 / 바인딩 값) |", "|---|---|---|---|"]
    for e in entries:
        ctrl = e["controller"] and f'`{e["controller"]["method"]}`<br>{e["controller"]["evidence"]}' or "-"
        sql = "<br>".join(
            f'{s["operation"]} {s["table"] or "(join)"} — `{s["mapper"]["id"].rsplit(".", 2)[-2] + "." + s["mapper"]["id"].rsplit(".", 1)[-1] if s["mapper"] else "매퍼 미확인"}` {s["bound_params"]}'
            for s in e["sql"]) or "-"
        req = f'{e["method"]} {e["route"]}' + (f'<br>`{e["query"]}`' if e["query"] else "")
        out.append(f'| {e["step"] or "-"} | {req} | {ctrl} | {sql} |')
    return "\n".join(out) + "\n"


def main():
    traces, src_root, out_dir = sys.argv[1:4]
    entries = correlate(load_spans(traces), src_root)
    out = Path(out_dir)
    (out / "endpoint-map.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "endpoint-map.md").write_text(to_markdown(entries), encoding="utf-8")
    unmatched = sum(1 for e in entries for s in e["sql"] if not s["mapper"])
    print(f"{len(entries)} endpoints, {sum(len(e['sql']) for e in entries)} SQL, unmatched mapper: {unmatched}")


if __name__ == "__main__":
    main()
