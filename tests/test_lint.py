"""린터가 해석 에이전트의 실수(환각·정책 위반)를 잡아내는지 확인한다."""

import pytest

from automcp.lint import ERROR, lint
from conftest import needs_source, tool

pytestmark = needs_source


def errors(spec):
    return [f for f in lint(spec) if f.level == ERROR]


def assert_error(spec, tool_name, fragment):
    found = [f for f in errors(spec) if f.tool == tool_name and fragment in f.message]
    assert found, f"'{fragment}' 오류가 없음: {[str(f) for f in errors(spec)]}"


def test_example_is_clean(example_data, write_spec):
    assert errors(write_spec(example_data)) == []


def test_schema_violation(example_data, write_spec):
    del tool(example_data, "search_products")["evidence"]
    assert any(f.tool == "(schema)" for f in errors(write_spec(example_data)))


def test_excluded_column(example_data, write_spec):
    t = tool(example_data, "list_customer_orders")
    t["binding"]["statement"] = t["binding"]["statement"].replace("o.courier,", "o.courier, o.creditcard,")
    assert_error(write_spec(example_data), "list_customer_orders", "orders.creditcard")


def test_excluded_column_without_alias(example_data, write_spec):
    t = tool(example_data, "list_customer_orders")
    t["binding"]["statement"] = "SELECT creditcard FROM orders WHERE userid = #{username} LIMIT 1"
    assert_error(write_spec(example_data), "list_customer_orders", "orders.creditcard")


def test_select_star(example_data, write_spec):
    tool(example_data, "get_product_details")["binding"]["statement"] = \
        "SELECT * FROM item WHERE productid = #{product_id} LIMIT 5"
    assert_error(write_spec(example_data), "get_product_details", "SELECT *")


def test_dml_in_read_tool(example_data, write_spec):
    tool(example_data, "get_product_details")["binding"]["statement"] = \
        "UPDATE inventory SET qty = 0 WHERE itemid = #{product_id}"
    assert_error(write_spec(example_data), "get_product_details", "SELECT 외")


def test_multiple_statements(example_data, write_spec):
    tool(example_data, "get_product_details")["binding"]["statement"] = \
        "SELECT itemid FROM item WHERE productid = #{product_id} LIMIT 5; DELETE FROM item"
    assert_error(write_spec(example_data), "get_product_details", "단일 문장")


def test_param_mismatch(example_data, write_spec):
    tool(example_data, "get_order")["input"]["extra"] = {"type": "string", "description": "쓰이지 않는 입력"}
    assert_error(write_spec(example_data), "get_order", "입력 파라미터 불일치")


def test_hallucinated_mapper(example_data, write_spec):
    tool(example_data, "search_products")["binding"]["reuse"] = ["ProductMapper.searchProductsFuzzy"]
    assert_error(write_spec(example_data), "search_products", "소스에 없는 매퍼")


def test_hallucinated_source_file(example_data, write_spec):
    tool(example_data, "search_products")["evidence"]["source"] = ["src/main/java/Nope.java:3"]
    assert_error(write_spec(example_data), "search_products", "근거 파일 없음")


def test_source_line_out_of_range(example_data, write_spec):
    ev = tool(example_data, "search_products")["evidence"]["source"]
    ev[0] = ev[0].rsplit(":", 1)[0] + ":99999"
    assert_error(write_spec(example_data), "search_products", "줄 번호")


def test_unknown_trace(example_data, write_spec):
    tool(example_data, "search_products")["evidence"]["capture"][0]["trace"] = "0" * 32
    assert_error(write_spec(example_data), "search_products", "캡처에 없는 trace")


def test_write_requires_policy(example_data, write_spec):
    example_data["policies"]["allow_write"] = False
    assert_error(write_spec(example_data), "place_order", "allow_write")


@pytest.mark.parametrize("db", ["oracle", "mysql", "mssql"])
def test_param_reuse_rejected_outside_postgres(example_data, write_spec, db):
    example_data["system"]["database"]["type"] = db
    t = tool(example_data, "list_customer_orders")
    t["binding"]["statement"] = ("SELECT o.orderid FROM orders o WHERE o.userid = #{username} "
                                 "OR o.billtofirstname = #{username} FETCH FIRST 5 ROWS ONLY")
    assert_error(write_spec(example_data), "list_customer_orders", "재사용 불가")
