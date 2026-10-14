import json
import shutil

from automcp import drift
from automcp.compile_toolbox import compile_spec
from automcp.har import sanitize
from conftest import SOURCE, needs_source


@needs_source
def test_drift_detects_mapper_change_and_line_move(example_data, write_spec, tmp_path):
    spec = write_spec(example_data)
    compile_spec(spec, tmp_path / "build", allow_pending=True)
    lock = tmp_path / "build" / "automcp.lock.json"

    new_src = tmp_path / "src-v2"
    shutil.copytree(SOURCE / "src", new_src / "src")
    assert all(not issues for issues in drift.detect(lock, new_src).values())

    # 매퍼 SQL 변경 → BREAKING
    mapper = new_src / "src/main/resources/org/mybatis/jpetstore/mapper/ProductMapper.xml"
    mapper.write_text(mapper.read_text(encoding="utf-8").replace(
        "WHERE lower(name) like #{value}", "WHERE upper(name) like #{value}"), encoding="utf-8")
    # 컨트롤러 위에 줄 삽입 → 근거 줄 이동(MOVED)
    ctrl = new_src / "src/main/java/org/mybatis/jpetstore/web/controllers/OrderController.java"
    ctrl.write_text("// 새 주석\n" + ctrl.read_text(encoding="utf-8"), encoding="utf-8")

    report = drift.detect(lock, new_src)
    assert any(level == "BREAKING" and "searchProductList" in msg for level, msg in report["search_products"])
    assert any(level == "MOVED" for level, _ in report["get_order"])
    assert report["get_product_details"] == []


def test_har_sanitize():
    har = {"log": {"entries": [{
        "request": {
            "url": "http://x/login?user=a&password=secret",
            "headers": [{"name": "Cookie", "value": "JSESSIONID=abc"}],
            "queryString": [{"name": "password", "value": "secret"}],
            "postData": {"mimeType": "application/x-www-form-urlencoded",
                         "text": "username=j2ee&password=j2ee&creditCard=999+9999",
                         "params": [{"name": "password", "value": "j2ee"}]},
        },
        "response": {
            "headers": [{"name": "Set-Cookie", "value": "JSESSIONID=abc"}],
            "content": {"mimeType": "text/html", "text": "<td>4111 1111 1111 1111</td><td>800101-1234567</td><td>Order #1000</td>"},
        },
    }]}}
    clean, stats = sanitize(har)
    text = json.dumps(clean)
    for secret in ("secret", "JSESSIONID", "password=j2ee", "4111 1111", "800101-1234567"):
        assert secret not in text, secret
    assert "Order #1000" in text  # 업무 데이터는 남김
    assert stats["headers"] == 2
