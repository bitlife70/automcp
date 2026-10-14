"""L1/L2 동적 검증: 실행 중인 MCP 서버를 MCP 프로토콜로 호출해 IR의 verify 항목을 점검한다.

- golden : 시연 HAR의 화면에서 정규식으로 뽑은 값 집합 == tool 결과 필드 값 집합
- cases  : 가드 검사 (행 수, 오류 여부, 금지 문자열 비노출)
"""

import json
import re
import urllib.request
from dataclasses import dataclass

from .ir import Spec, tool_matches


class McpClient:
    """Streamable HTTP MCP 최소 클라이언트 (JSON 또는 SSE 응답 모두 처리)."""

    def __init__(self, url, timeout=30, headers=None):
        self.url, self.timeout, self.session, self.next_id = url, timeout, None, 1
        self.headers = headers or {}

    def _post(self, payload):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            self.session = resp.headers.get("Mcp-Session-Id") or self.session
            body = resp.read().decode("utf-8")
            if resp.headers.get("Content-Type", "").startswith("text/event-stream"):
                data = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
                body = data[-1] if data else "{}"
            return json.loads(body) if body.strip() else {}

    def request(self, method, params=None):
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        resp = self._post(msg)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp["result"]

    def initialize(self):
        result = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "automcp-verify", "version": "0.1.0"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self):
        return self.request("tools/list")["tools"]

    def call(self, name, args):
        """(is_error, rows, raw_text) — 결과 텍스트가 JSON이면 행 목록으로 펼친다."""
        result = self.request("tools/call", {"name": name, "arguments": args})
        rows, texts = [], []
        for c in result.get("content", []):
            if c.get("type") != "text":
                continue
            texts.append(c["text"])
            try:
                v = json.loads(c["text"])
            except json.JSONDecodeError:
                v = c["text"]
            if v in (None, "null"):
                continue
            rows.extend(v if isinstance(v, list) else [v])
        return result.get("isError", False), rows, "\n".join(texts)


@dataclass
class Check:
    tool: str
    name: str
    ok: bool
    detail: str


def har_page(har, step):
    """시연 단계의 마지막 HTML 응답(= 그 단계의 결과 화면)."""
    pages = []
    for e in har["log"]["entries"]:
        hdr = {h["name"].lower(): h["value"] for h in e["request"]["headers"]}
        content = e["response"].get("content", {})
        if hdr.get("x-automcp-step") == step and content.get("mimeType", "").startswith("text/html"):
            pages.append(content.get("text", ""))
    if not pages:
        raise LookupError(f"HAR에 단계 {step}의 HTML 응답이 없음")
    return pages[-1]


def _fmt(value, fmt):
    if fmt:
        try:
            return fmt.format(float(value)) if "f}" in fmt else fmt.format(value)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def run(spec: Spec, urls, tools=None, headers=None):
    """urls: MCP 서버 URL 목록. tool은 그것을 등록한 서버로 라우팅한다(예: Toolbox + flow 런타임, 또는 게이트웨이 하나)."""
    checks = []
    route = {}  # IR tool 이름 → (client, 서버 측 이름)
    for url in [urls] if isinstance(urls, str) else urls:
        client = McpClient(url, headers=headers)
        client.initialize()
        for t in client.list_tools():
            for ir_tool in spec.tools:
                if tool_matches(ir_tool["name"], t["name"]):
                    route.setdefault(ir_tool["name"], (client, t["name"]))
    listed = set(route)
    har = json.loads(spec.har_path.read_text(encoding="utf-8")) if spec.har_path and spec.har_path.exists() else None

    for tool in spec.tools:
        name = tool["name"]
        if tools and name not in tools:
            continue
        if name not in listed:
            checks.append(Check(name, "서버 등록", False, "MCP 서버에 tool 없음 (미승인 또는 미배포)"))
            continue
        v = tool.get("verify", {})
        client, remote = route[name]

        class _Bound:  # IR 이름으로 호출하면 서버 측 이름으로 바꿔 보낸다
            @staticmethod
            def call(_name, args):
                return client.call(remote, args)

        mcp = _Bound

        g = v.get("golden")
        if g:
            if har is None:
                checks.append(Check(name, "golden", False, "system.har 없음"))
            else:
                is_err, rows, raw = mcp.call(name, g["args"])
                expected = set(re.findall(g["page_regex"], har_page(har, g["step"])))
                actual = {_fmt(r.get(g["field"]), g.get("format")) for r in rows if isinstance(r, dict)}
                # contains: 캡처 값이 모두 tool 결과에 있어야 함(이후 데이터가 늘어나는 목록용)
                ok = not is_err and (expected == actual if g.get("match", "set_equal") == "set_equal"
                                     else bool(expected) and expected <= actual)
                checks.append(Check(name, f"golden {g['args']}", ok,
                                    f"캡처 {sorted(expected)} / tool {sorted(actual)}" + (f" / 오류 {raw[:200]}" if is_err else "")))

        for case in v.get("cases", []):
            is_err, rows, raw = mcp.call(name, case["args"])
            exp, problems = case["expect"], []
            if "is_error" in exp and is_err != exp["is_error"]:
                problems.append(f"is_error={is_err}")
            if not exp.get("is_error") and is_err:
                problems.append(f"오류 응답: {raw[:200]}")
            if "rows" in exp and len(rows) != exp["rows"]:
                problems.append(f"rows={len(rows)} (기대 {exp['rows']})")
            if "min_rows" in exp and len(rows) < exp["min_rows"]:
                problems.append(f"rows={len(rows)} (최소 {exp['min_rows']})")
            leaked = [s for s in exp.get("not_contains", []) if s.lower() in raw.lower()]
            if leaked:
                problems.append(f"노출: {leaked}")
            checks.append(Check(name, case["name"], not problems, "; ".join(problems) or f"{len(rows)}행"))
    return checks
