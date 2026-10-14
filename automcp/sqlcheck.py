"""SQL 바인딩의 정적 검사 (sqlglot).

에이전트가 쓴 SQL이 정책을 어기지 않는지 실행 전에 결정적으로 확인한다.
- read tool은 단일 SELECT만 허용 (DML/DDL, 다중 문장 금지)
- SELECT * 금지 (스키마 변경 시 민감 컬럼이 새어 나가는 것을 막음)
- 정책상 제외 컬럼 참조 금지
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from .ir import PARAM_RE

DIALECT = {"postgres": "postgres", "oracle": "oracle", "mysql": "mysql", "mssql": "tsql"}
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.Command)


@dataclass
class SqlFacts:
    tables: set = field(default_factory=set)      # 실제 테이블명(소문자)
    columns: set = field(default_factory=set)     # (테이블명, 컬럼명) — 테이블을 못 정하면 테이블명 None
    is_select_only: bool = True
    has_star: bool = False
    has_limit: bool = False
    statements: int = 1


def analyze(statement, db_type):
    """#{param}을 NULL로 치환해 파싱하고 테이블·컬럼·문장 성격을 추출한다. 파싱 실패 시 예외."""
    sql = PARAM_RE.sub("NULL", statement)
    trees = [t for t in sqlglot.parse(sql, read=DIALECT[db_type]) if t is not None]
    facts = SqlFacts(statements=len(trees))
    for tree in trees:
        if not isinstance(tree, (exp.Select, exp.Union)) or any(True for _ in tree.find_all(*WRITE_NODES)):
            facts.is_select_only = False
        alias_to_table = {}
        for t in tree.find_all(exp.Table):
            if t.name:
                facts.tables.add(t.name.lower())
                alias_to_table[t.alias_or_name.lower()] = t.name.lower()
        single_table = next(iter(facts.tables)) if len(facts.tables) == 1 else None
        for c in tree.find_all(exp.Column):
            if isinstance(c.this, exp.Star):
                facts.has_star = True
                continue
            table = alias_to_table.get(c.table.lower()) if c.table else single_table
            facts.columns.add((table, c.name.lower()))
        for s in tree.find_all(exp.Select):
            if any(isinstance(e, exp.Star) for e in s.expressions):
                facts.has_star = True
        facts.has_limit = facts.has_limit or any(True for _ in tree.find_all(exp.Limit, exp.Fetch)) or bool(
            tree.args.get("limit"))
    return facts


def excluded_hits(facts, excluded):
    """정책 제외 컬럼(table.col) 참조 목록. 테이블을 특정 못한 컬럼은 컬럼명만으로 보수적으로 판정."""
    hits = []
    for rule in excluded:
        table, col = rule.split(".", 1)
        for t, c in facts.columns:
            if c == col and (t == table or (t is None and table in facts.tables)):
                hits.append(rule)
    return sorted(set(hits))
