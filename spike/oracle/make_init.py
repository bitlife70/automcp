"""jpetstore 카탈로그 스키마·데이터(HSQLDB 스크립트)를 Oracle용 초기화 SQL로 변환한다 (sqlglot 트랜스파일).

  python make_init.py <jpetstore 소스 루트> <출력 .sql>

주문 계열 테이블은 컬럼명 "timestamp"가 Oracle 예약어라 제외하고, 카탈로그 테이블만 옮긴다.
"""
import re
import sys
from pathlib import Path

import sqlglot

TABLES = ["supplier", "category", "product", "item", "inventory"]


def statements(path):
    text = re.sub(r"--[^\n]*", "", Path(path).read_text(encoding="utf-8"))
    return [s.strip() for s in text.split(";") if s.strip()]


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    db = root / "src/main/resources/database"
    lines = ["-- 생성물: spike/oracle/make_init.py", "SET DEFINE OFF",
             "ALTER SESSION SET CONTAINER = FREEPDB1;", "ALTER SESSION SET CURRENT_SCHEMA = JPETSTORE;"]
    for s in statements(db / "jpetstore-hsqldb-schema.sql"):
        m = re.match(r"create\s+(table|index)\s+(\w+)(?:\s+on\s+(\w+))?", s, re.I)
        if not m:
            continue
        table = (m.group(3) or m.group(2)).lower()
        if table in TABLES:
            lines.append(sqlglot.transpile(s, read="postgres", write="oracle")[0] + ";")
    for s in statements(db / "jpetstore-hsqldb-dataload.sql"):
        m = re.match(r"insert\s+into\s+(\w+)", s, re.I)
        if m and m.group(1).lower() in TABLES:
            lines.append(s + ";")
    lines += ["COMMIT;",
              "CREATE USER mcp_reader IDENTIFIED BY \"mcp_reader_dev_only\";",
              "GRANT CREATE SESSION TO mcp_reader;"]
    lines += [f"GRANT SELECT ON jpetstore.{t} TO mcp_reader;" for t in ["category", "product", "item", "inventory"]]
    lines += ["ALTER USER mcp_reader DEFAULT ROLE ALL;", "exit;"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}: {len(lines)} lines")


if __name__ == "__main__":
    main()
