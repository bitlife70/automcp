"""http-flow 런타임: 가짜 레거시 서버(httpx.MockTransport)로 세션·폼·문자셋·멱등성·오류 전달을 확인한다."""

import asyncio
import urllib.parse

import httpx
import pytest

from automcp.runtime.flow import FlowError, FlowRunner, IdempotencyStore, prefilled_form

FORM_PAGE = """
<form method="post" action="/app/order/new">
  <select name="cardType"><option>Visa</option><option selected>Master</option></select>
  <input type="text" name="creditCard" value="999 9999 9999 9999"/>
  <input type="text" name="billCity" value="서울"/>
  <input type="checkbox" name="shippingAddressRequired" value="true"/>
  <input type="checkbox" name="agree" value="Y" checked/>
  <input type="submit" name="newOrder" value="Continue"/>
</form>"""


class FakeLegacy:
    """세션 쿠키가 있어야 주문 가능한 EUC-KR 레거시 웹."""

    def __init__(self, charset="euc-kr"):
        self.charset, self.orders, self.calls = charset, 0, []

    def __call__(self, request: httpx.Request):
        path, cookie = request.url.path, request.headers.get("cookie", "")
        body = urllib.parse.parse_qs(request.content.decode("ascii"), encoding=self.charset) if request.content else {}
        self.calls.append((request.method, path, body))
        html = lambda s, code=200, **kw: httpx.Response(code, content=s.encode(self.charset), **kw)
        if path == "/app/login":
            ok = body.get("username") == ["kim"] and body.get("password") == ["pw"]
            return httpx.Response(302, headers={"set-cookie": "SID=1; Path=/", "location": "/app"}) if ok \
                else html("로그인 실패")
        if "SID=1" not in cookie:
            return html("세션 만료", 302, headers={"location": "/app/login"})
        if path == "/app/cart/add":
            item = request.url.params.get("item")
            return html("장바구니") if item == "EST-1" else html("상품 없음", 500)
        if path == "/app/order/new" and request.method == "GET":
            return html(FORM_PAGE)
        if path == "/app/order/new" and body.get("confirmed") == ["true"]:
            self.orders += 1
            return html(f"주문이 접수되었습니다. Order #{1000 + self.orders} Total: $33.00")
        if path == "/app/order/new":
            assert body["creditCard"] == ["999 9999 9999 9999"] and body["cardType"] == ["Master"]
            assert body["billCity"] == ["서울"] and "shippingAddressRequired" not in body
            return html('<form action="/app/order/new"><input name="confirmed" value="true"/></form>Confirm')
        return html("없음", 404)


TOOL = {
    "name": "place_order",
    "idempotency_key": "request_id",
    "session": {"login": {"method": "POST", "path": "/login",
                          "form": {"username": "${env:U}", "password": "${env:P}"}, "expect": {"status": [302]}}},
    "steps": [
        {"name": "add", "method": "GET", "path": "/cart/add?item={item_id}", "expect": {"contains": "장바구니"}},
        {"name": "form", "method": "GET", "path": "/order/new", "expect": {"contains": "creditCard"}},
        {"name": "submit", "method": "POST", "path": "/order/new", "form": "@prefilled", "expect": {"contains": "Confirm"}},
        {"name": "confirm", "method": "POST", "path": "/order/new", "form": {"confirmed": "true"},
         "expect": {"contains": "주문이 접수되었습니다.",
                    "extract": {"order_id": r"Order #(\d+)", "total_price": r"Total: \$([\d.]+)"}}},
    ],
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("U", "kim")
    monkeypatch.setenv("P", "pw")


def runner(legacy, tmp_path):
    cfg = {"base_url": "http://legacy/app", "charset": "euc-kr"}
    return FlowRunner(cfg, store=IdempotencyStore(tmp_path / "s.db"), transport=httpx.MockTransport(legacy))


def test_flow_success_and_idempotency(env, tmp_path):
    legacy = FakeLegacy()
    r = runner(legacy, tmp_path)
    first = asyncio.run(r.run(TOOL, {"item_id": "EST-1", "request_id": "req-1"}))
    assert first == {"order_id": "1001", "total_price": "33.00", "message": "주문이 접수되었습니다.", "replayed": False}
    again = asyncio.run(r.run(TOOL, {"item_id": "EST-1", "request_id": "req-1"}))
    assert again["order_id"] == "1001" and again["replayed"] is True
    assert legacy.orders == 1  # 재호출로 재주문하지 않음
    asyncio.run(r.run(TOOL, {"item_id": "EST-1", "request_id": "req-2"}))
    assert legacy.orders == 2


def test_flow_error_is_actionable(env, tmp_path):
    with pytest.raises(FlowError) as e:
        asyncio.run(runner(FakeLegacy(), tmp_path).run(TOOL, {"item_id": "NOPE", "request_id": "x"}))
    assert e.value.step == "add" and "HTTP 500" in str(e.value) and "상품 없음" in str(e.value)


def test_missing_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("U", raising=False)
    with pytest.raises(FlowError, match="환경변수 U"):
        asyncio.run(runner(FakeLegacy(), tmp_path).run(TOOL, {"item_id": "EST-1", "request_id": "y"}))


def test_prefilled_form_parser():
    fields = dict(prefilled_form(FORM_PAGE, "/app/order/new"))
    assert fields == {"cardType": "Master", "creditCard": "999 9999 9999 9999", "billCity": "서울", "agree": "Y"}
    assert prefilled_form(FORM_PAGE, "/other") is None
