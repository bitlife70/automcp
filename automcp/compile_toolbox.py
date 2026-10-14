"""IR → 런타임 설정 컴파일러.

결정적 변환만 한다(LLM 없음).
- sql 바인딩       → MCP Toolbox 설정(tools.yaml)
- http-flow 바인딩 → automcp flow 런타임 설정(flows.yaml)
승인(review.status=approved)되지 않은 tool은 기본적으로 제외한다.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

from . import correlate
from .ir import PARAM_RE, Spec, statement_params

PLACEHOLDER = {
    "postgres": lambda i: f"${i}",
    "oracle": lambda i: f":{i}",
    "mysql": lambda i: "?",
    "mssql": lambda i: f"@p{i}",
}

HEADER = """\
# 생성물 — 직접 수정하지 말 것. 원본: {ir}
# automcp {version} / {generated}
# 변경은 IR(mcp-spec.yaml)을 고친 뒤 `automcp compile`로 다시 생성한다.
"""


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def _dump(doc):
    return yaml.dump(doc, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)


def _oracle_lowercase_aliases(statement):
    """Oracle은 따옴표 없는 별칭을 대문자로 돌려준다(product_id → PRODUCT_ID).
    IR의 출력 필드 이름이 그대로 나오도록 최상위 SELECT 컬럼에 소문자 따옴표 별칭을 붙인다."""
    named = PARAM_RE.sub(lambda m: f":{m.group(1)}", statement)
    tree = sqlglot.parse_one(named, read="oracle")
    if not isinstance(tree, exp.Select):
        return statement
    for i, e in enumerate(tree.expressions):
        target = e.this if isinstance(e, exp.Alias) else e
        tree.expressions[i] = exp.alias_(target, exp.to_identifier(e.alias_or_name.lower(), quoted=True))
    sql = tree.sql(dialect="oracle", pretty=True)
    for name in sorted(set(statement_params(statement)), key=len, reverse=True):
        sql = re.sub(rf":{name}\b", "#{" + name + "}", sql)
    return sql


def render_statement(statement, db_type):
    """#{name} → DB 방언 위치 파라미터. 파라미터 순서(첫 등장 순)를 함께 반환한다."""
    if db_type == "oracle":
        statement = _oracle_lowercase_aliases(statement)
    order = list(dict.fromkeys(statement_params(statement)))
    index = {name: i + 1 for i, name in enumerate(order)}
    sql = PARAM_RE.sub(lambda m: PLACEHOLDER[db_type](index[m.group(1)]), statement)
    return sql.strip() + "\n", order


def tool_doc(tool, spec):
    sql, order = render_statement(tool["binding"]["statement"], spec.db_type)
    params = []
    for name in order:
        p = tool["input"][name]
        params.append({"name": name, "type": p["type"], "description": p["description"]})
    return {
        "kind": "tool",
        "name": tool["name"],
        "type": f"{spec.db_type}-sql",
        "source": spec.data["system"]["database"]["source_name"],
        "description": " ".join(tool["description"].split()),
        "parameters": params,
        "statement": sql,
    }


def flow_doc(tool):
    """http-flow tool → automcp flow 런타임 설정 항목."""
    b = tool["binding"]
    doc = {
        "name": tool["name"],
        "description": " ".join(tool["description"].split()),
        "side_effect": tool["side_effect"],
        "input": tool["input"],
        "session": b.get("session", {}),
        "steps": b["steps"],
    }
    if "request_id" in tool["input"]:
        doc["idempotency_key"] = "request_id"
    return doc


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def fingerprints(spec, tool, mappers):
    """drift 감지용 지문: 재사용 매퍼 SQL과 근거 소스 줄의 해시."""
    fp = {"mappers": {}, "source": {}}
    by_id = {}
    for m in mappers or []:
        by_id[m["id"]] = m
        by_id[m["id"].rsplit(".", 2)[-2] + "." + m["id"].rsplit(".", 1)[-1]] = m
    for ref in tool["binding"].get("reuse", []):
        if ref in by_id:
            fp["mappers"][ref] = _sha(by_id[ref]["sql"])
    root = spec.source_root
    for ref in tool["evidence"]["source"]:
        file, line = ref.rsplit(":", 1)
        path = root / file if root else None
        if path and path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if int(line) <= len(lines):
                fp["source"][ref] = _sha(lines[int(line) - 1].strip())
    return fp


def compile_spec(spec: Spec, out_dir, allow_pending=False):
    """tools.yaml과 automcp.lock.json을 쓴다. (포함된 tool, 제외 사유) 반환."""
    from . import __version__

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = spec.data["system"]["database"]
    docs = [{"kind": "source", "name": db["source_name"], "type": db["type"], **db["connection"]}]
    included, skipped, flows = [], {}, []
    for tool in spec.tools:
        status = tool["review"]["status"]
        if status == "rejected" or (status == "pending" and not allow_pending):
            skipped[tool["name"]] = f"검토 상태 {status}"
        elif tool["binding"]["kind"] == "sql":
            docs.append(tool_doc(tool, spec))
            included.append(tool)
        else:
            flows.append(flow_doc(tool))
            included.append(tool)
    sql_tools = [t["name"] for t in included if t["binding"]["kind"] == "sql"]
    if sql_tools:
        docs.append({"kind": "toolset", "name": spec.data["agent"]["name"], "tools": sql_tools})

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = HEADER.format(ir=spec.path.name, version=__version__, generated=now)
    (out / "tools.yaml").write_text(header + "---\n".join(_dump(d) for d in docs), encoding="utf-8")
    flows_path = out / "flows.yaml"
    if flows:
        http = spec.data["system"]["http"]
        flow_cfg = {"runtime": "automcp-flow/v1", "name": f"{spec.data['agent']['name']}-flows",
                    "base_url": http["base_url"], "charset": http.get("charset", "UTF-8"), "tools": flows}
        flows_path.write_text(header + _dump(flow_cfg), encoding="utf-8")
    elif flows_path.exists():
        flows_path.unlink()

    mappers = correlate.index_mappers(spec.source_root) if spec.source_root and spec.source_root.exists() else None
    lock = {
        "ir": spec.path.name,
        "ir_sha": _sha(spec.path.read_text(encoding="utf-8")),
        "generated": now,
        "tools": {t["name"]: {"review": t["review"]["status"], **fingerprints(spec, t, mappers)} for t in included},
    }
    (out / "automcp.lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return included, skipped
