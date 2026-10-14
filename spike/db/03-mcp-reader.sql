-- MCP 런타임 전용 최소권한 계정.
-- 앱 계정(jpetstore)과 분리하고, 에이전트에 필요한 테이블/컬럼만 SELECT 허용한다.
-- 카드번호(creditcard), 유효기간(exprdate), 카드종류(cardtype)는 컬럼 권한에서 제외해
-- tools.yaml이 실수로 조회하더라도 DB 단에서 거부되도록 한다(심층 방어).

CREATE ROLE mcp_reader LOGIN PASSWORD 'mcp_reader_dev_only';

GRANT SELECT ON category, product, item, inventory, lineitem, orderstatus TO mcp_reader;

GRANT SELECT (
  orderid, userid, orderdate,
  shipaddr1, shipaddr2, shipcity, shipstate, shipzip, shipcountry,
  billaddr1, billaddr2, billcity, billstate, billzip, billcountry,
  courier, totalprice, billtofirstname, billtolastname, shiptofirstname, shiptolastname, locale
) ON orders TO mcp_reader;
