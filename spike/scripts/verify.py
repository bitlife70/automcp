"""검증 하네스: 생성된 MCP 서버를 실제 MCP 프로토콜로 호출해 IR의 verify 항목을 점검한다.

1) golden replay : 시연 때 캡처한 화면 응답(HAR)과 tool 결과를 비교 (테스트 데이터 작성 비용 0)
2) guard 검사     : 소유자 검증, 파라미터 바인딩(SQL 인젝션), 민감 컬럼 비노출

사용: python verify.py <mcp-spec.yaml> <demo.har> <mcp_url>
"""

import json
import re
import sys
import urllib.request

import yaml


class McpClient:
    """Streamable HTTP MCP 최소 클라이언트 (JSON 또는 SSE 응답 모두 처리)."""

    def __init__(self, url):
        self.url, self.session, self.next_id = url, None, 1

    def _post(self, payload):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
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
            "clientInfo": {"name": "automcp-verify", "version": "0.0.1"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call(self, name, args):
        result = self.request("tools/call", {"name": name, "arguments": args})
        rows = []
        for c in result.get("content", []):
            if c.get("type") != "text":
                continue
            try:
                v = json.loads(c["text"])
            except json.JSONDecodeError:
                v = c["text"]
            rows.extend(v if isinstance(v, list) else [v])
        return result.get("isError", False), rows


def har_page(har, step):
    """시연 단계의 마지막 HTML 응답(= 그 단계의 결과 화면)."""
    pages = []
    for e in har["log"]["entries"]:
        hdr = {h["name"].lower(): h["value"] for h in e["request"]["headers"]}
        content = e["response"].get("content", {})
        if hdr.get("x-automcp-step") == step and content.get("mimeType", "").startswith("text/html"):
            pages.append(content.get("text", ""))
    if not pages:
        raise LookupError(f"HAR에 단계 {step} 의 HTML 응답이 없음")
    return pages[-1]


def ids_in_page(html, param):
    return set(re.findall(rf"{param}=([A-Za-z0-9-]+)", html))


COMPARATORS = {
    "product_ids_in_page": lambda html, rows: (ids_in_page(html, "productId"), {r["product_id"] for r in rows}),
    "item_ids_in_page": lambda html, rows: (ids_in_page(html, "itemId"), {r["item_id"] for r in rows}),
    "order_ids_in_page": lambda html, rows: (ids_in_page(html, "orderId"), {str(r["order_id"]) for r in rows}),
    "order_total_in_page": lambda html, rows: (
        {m for m in re.findall(r"\$\s*([\d,]+\.\d{2})", html)} & {f'{float(r["total_price"]):.2f}' for r in rows} or {"<불일치>"},
        {f'{float(r["total_price"]):.2f}' for r in rows},
    ),
}


def main():
    spec_path, har_path, url = sys.argv[1:4]
    spec = yaml.safe_load(open(spec_path, encoding="utf-8"))
    har = json.load(open(har_path, encoding="utf-8"))
    mcp = McpClient(url)
    info = mcp.initialize()
    listed = {t["name"] for t in mcp.request("tools/list")["tools"]}
    print(f"MCP server: {info.get('serverInfo')}  tools: {sorted(listed)}\n")

    results = []

    def check(name, ok, detail):
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    print("1) IR ↔ 서버 tool 목록")
    declared = {t["name"] for t in spec["tools"]}
    check("tool 목록 일치", declared == listed, f"IR {len(declared)}개 / 서버 {len(listed)}개")

    print("2) golden replay (시연 캡처 vs tool 결과)")
    for tool in spec["tools"]:
        g = tool.get("verify", {}).get("golden")
        if not g:
            continue
        is_err, rows = mcp.call(tool["name"], g["args"])
        expected, actual = COMPARATORS[g["compare"]](har_page(har, g["step"]), rows)
        check(f'{tool["name"]}{g["args"]}', not is_err and expected == actual,
              f"캡처 {sorted(expected)} / tool {sorted(actual)}")

    print("3) guard 검사")
    _, rows = mcp.call("get_order", {"order_id": 1000, "username": "ACID"})
    check("소유자 불일치 주문 조회 차단", rows == [] or rows == [None] or rows == ["null"], f"결과 {rows}")
    # 공백이 없는 단일 토큰 페이로드를 쓴다(공백이 있으면 'or' 같은 토큰이 정상 검색어로 매칭됨).
    for payload in ["zzz'||'", "x');DROP/**/TABLE/**/product;--"]:
        is_err, rows = mcp.call("search_products", {"keyword": payload})
        check(f"SQL 인젝션 무력화 {payload!r}", not is_err and rows in ([], ["null"]), f"결과 {len(rows)}행")
    _, rows = mcp.call("search_products", {"keyword": "fish"})
    check("인젝션 시도 후 product 테이블 정상", len(rows) == 2, f"fish 검색 {len(rows)}행")
    leaked = set()
    for t, args in [("list_customer_orders", {"username": "j2ee"}), ("get_order", {"order_id": 1000, "username": "j2ee"})]:
        _, rows = mcp.call(t, args)
        text = json.dumps(rows, ensure_ascii=False).lower()
        leaked |= {c for c in ("creditcard", "exprdate", "cardtype", "9999") if c in text}
    check("결제수단 정보 비노출", not leaked, f"노출 항목 {sorted(leaked) or '없음'}")

    passed = sum(results)
    print(f"\n결과: {passed}/{len(results)} 통과")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
