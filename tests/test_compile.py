import json

import pytest
import yaml

from automcp.compile_toolbox import compile_spec, render_statement
from conftest import needs_source, tool


def test_oracle_aliases_are_lowercase_quoted():
    sql, order = render_statement(
        "SELECT p.productid AS product_id, p.name FROM product p WHERE p.category = #{cat} AND p.name LIKE #{kw}",
        "oracle")
    assert 'AS "product_id"' in sql and 'AS "name"' in sql
    assert ":1" in sql and ":2" in sql and "#{" not in sql
    assert order == ["cat", "kw"]


@pytest.mark.parametrize("db,expected", [
    ("postgres", "a = $1 AND b = $2 OR a2 = $1"),
    ("oracle", "a = :1 AND b = :2 OR a2 = :1"),
    ("mysql", "a = ? AND b = ? OR a2 = ?"),
    ("mssql", "a = @p1 AND b = @p2 OR a2 = @p1"),
])
def test_placeholders(db, expected):
    sql, order = render_statement("a = #{x} AND b = #{ y } OR a2 = #{x}", db)
    assert sql.strip() == expected
    assert order == ["x", "y"]


@needs_source
def test_review_gate(example_data, write_spec, tmp_path):
    tool(example_data, "search_products")["review"] = {"status": "approved", "by": "운영자", "at": "2026-10-14"}
    tool(example_data, "get_order")["review"] = {"status": "rejected"}
    spec = write_spec(example_data)
    included, skipped = compile_spec(spec, tmp_path / "build")
    assert [t["name"] for t in included] == ["search_products"]
    assert "pending" in skipped["get_product_details"]
    assert "rejected" in skipped["get_order"]
    assert "pending" in skipped["place_order"]
    assert not (tmp_path / "build" / "flows.yaml").exists()


@needs_source
def test_compiled_tools_yaml(example_data, write_spec, tmp_path):
    spec = write_spec(example_data)
    compile_spec(spec, tmp_path / "build", allow_pending=True)
    docs = list(yaml.safe_load_all((tmp_path / "build" / "tools.yaml").read_text(encoding="utf-8")))
    kinds = [d["kind"] for d in docs]
    assert kinds[0] == "source" and kinds[-1] == "toolset"
    get_order = next(d for d in docs if d.get("name") == "get_order")
    assert get_order["type"] == "postgres-sql"
    assert [p["name"] for p in get_order["parameters"]] == ["order_id", "username"]
    assert "o.orderid = $1 AND o.userid = $2" in get_order["statement"]
    assert "#{" not in (tmp_path / "build" / "tools.yaml").read_text(encoding="utf-8")
    assert docs[0]["password"] == "${MCP_DB_PASSWORD}"  # 비밀값은 환경변수 참조로만


@needs_source
def test_lock_fingerprints(example_data, write_spec, tmp_path):
    spec = write_spec(example_data)
    compile_spec(spec, tmp_path / "build", allow_pending=True)
    lock = json.loads((tmp_path / "build" / "automcp.lock.json").read_text(encoding="utf-8"))
    fp = lock["tools"]["search_products"]
    assert set(fp["mappers"]) == {"ProductMapper.searchProductList"}
    assert len(fp["source"]) == 3


@needs_source
def test_flows_yaml(example_data, write_spec, tmp_path):
    tool(example_data, "place_order")["review"] = {"status": "approved"}
    included, _ = compile_spec(write_spec(example_data), tmp_path / "build")
    assert [t["name"] for t in included] == ["place_order"]
    flows = yaml.safe_load((tmp_path / "build" / "flows.yaml").read_text(encoding="utf-8"))
    po = flows["tools"][0]
    assert po["idempotency_key"] == "request_id"
    assert po["steps"][3]["form"] == "@prefilled"
    assert flows["base_url"].endswith("/jpetstore")
