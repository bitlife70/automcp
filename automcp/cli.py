"""automcp CLI.

  automcp sanitize-har <raw.har> <clean.har>           캡처 HAR 정제(자격증명·결제정보 제거)
  automcp correlate <traces.jsonl> --source D --out D  트레이스 ↔ 소스 상관분석 → 엔드포인트 맵
  automcp lint <mcp-spec.yaml>                         L0 정적 검증
  automcp compile <mcp-spec.yaml> --out D              IR → tools.yaml (+ lock)
  automcp verify <mcp-spec.yaml> --url U [--url U2]    실행 중인 MCP 서버 검증(golden + guard)
  automcp eval <eval.yaml> --url U [--url U2]          L3 에이전트 평가(claude -p)
  automcp contract <mcp-spec.yaml> --out F             운영자 검토용 인터페이스 계약서(HTML)
  automcp drift <automcp.lock.json> --source D         소스 변경 영향 분석
"""

import argparse
import sys

from . import ir


def _print_findings(findings):
    from .lint import ERROR, WARN

    for f in findings:
        print(f)
    e = sum(f.level == ERROR for f in findings)
    w = sum(f.level == WARN for f in findings)
    print(f"\nlint: 오류 {e} / 경고 {w}")
    return e


def cmd_sanitize_har(a):
    from .har import sanitize_file

    stats = sanitize_file(a.src, a.dst)
    print(f"정제 완료 → {a.dst}  (헤더 {stats['headers']}, 파라미터 {stats['params']}, 본문 {stats['bodies']}건 마스킹)")


def cmd_correlate(a):
    from . import correlate

    entries, unmatched = correlate.run(a.traces, a.source, a.out)
    n_sql = sum(len(e["sql"]) for e in entries)
    print(f"엔드포인트 {len(entries)}개, SQL {n_sql}개, 매퍼 미매칭 {unmatched}개 → {a.out}/endpoint-map.md")


def cmd_lint(a):
    from .lint import lint

    return 1 if _print_findings(lint(ir.load(a.spec))) else 0


def cmd_compile(a):
    from .compile_toolbox import compile_spec
    from .lint import ERROR, lint

    spec = ir.load(a.spec)
    findings = lint(spec)
    if any(f.level == ERROR for f in findings):
        _print_findings(findings)
        print("컴파일 중단: lint 오류를 먼저 해결하세요.")
        return 1
    included, skipped = compile_spec(spec, a.out, allow_pending=a.allow_pending)
    for t in included:
        flag = "" if t["review"]["status"] == "approved" else "  ⚠ 미승인(--allow-pending)"
        print(f"  + {t['name']}{flag}")
    for name, why in skipped.items():
        print(f"  - {name}: {why}")
    n_sql = sum(t["binding"]["kind"] == "sql" for t in included)
    outputs = [f"{a.out}/tools.yaml (sql {n_sql}개)"]
    if len(included) > n_sql:
        outputs.append(f"{a.out}/flows.yaml (http-flow {len(included) - n_sql}개)")
    print("→ " + ", ".join(outputs + [f"{a.out}/automcp.lock.json"]))
    return 0


def _headers(a):
    if getattr(a, "bearer_file", None):
        from pathlib import Path

        return {"Authorization": "Bearer " + Path(a.bearer_file).read_text(encoding="utf-8").strip()}
    return None


def cmd_verify(a):
    from .verify import run

    checks = run(ir.load(a.spec), a.url, tools=a.tool, headers=_headers(a))
    for c in checks:
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.tool} · {c.name}: {c.detail}")
    passed = sum(c.ok for c in checks)
    print(f"\nverify: {passed}/{len(checks)} 통과")
    return 0 if passed == len(checks) else 1


def cmd_eval(a):
    from .evaluate import run

    outcomes = run(a.eval_file, a.url, only=a.only, model=a.model, headers=_headers(a))
    for o in outcomes:
        print(f"  [{'PASS' if o.ok else 'FAIL'}] {o.id}  tools={o.tools}  {o.seconds:.0f}s ${o.cost_usd:.3f}")
        for pr in o.problems:
            print(f"      - {pr}")
        print("      답변: " + " ".join(o.answer.split())[:220])
    passed = sum(o.ok for o in outcomes)
    print(f"\neval: {passed}/{len(outcomes)} 통과, 비용 ${sum(o.cost_usd for o in outcomes):.3f}")
    return 0 if passed == len(outcomes) else 1


def cmd_contract(a):
    from .contract import render

    render(ir.load(a.spec), a.out)
    print(f"계약서 → {a.out}")


def cmd_drift(a):
    from .drift import detect

    report = detect(a.lock, a.source)
    worst = 0
    for tool, issues in report.items():
        if not issues:
            print(f"  ✔ {tool}")
        for level, msg in issues:
            print(f"  [{level}] {tool}: {msg}")
            worst = max(worst, 2 if level == "BREAKING" else 1)
    print("\ndrift:", {0: "변경 없음", 1: "근거 위치만 갱신 필요", 2: "재검토·재생성 필요"}[worst])
    return 1 if worst == 2 else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="automcp", description="레거시 → MCP 생성·검증 도구")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sanitize-har", help="캡처 HAR 정제")
    s.add_argument("src"), s.add_argument("dst")
    s.set_defaults(fn=cmd_sanitize_har)

    s = sub.add_parser("correlate", help="트레이스 ↔ 소스 상관분석")
    s.add_argument("traces"), s.add_argument("--source", required=True), s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_correlate)

    s = sub.add_parser("lint", help="IR 정적 검증")
    s.add_argument("spec")
    s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("compile", help="IR → tools.yaml")
    s.add_argument("spec"), s.add_argument("--out", required=True)
    s.add_argument("--allow-pending", action="store_true", help="개발용: 미승인 tool도 포함")
    s.set_defaults(fn=cmd_compile)

    s = sub.add_parser("verify", help="MCP 서버 동적 검증")
    s.add_argument("spec"), s.add_argument("--url", required=True, action="append", help="MCP 서버 URL (반복 가능)")
    s.add_argument("--tool", action="append", help="특정 tool만 (반복 가능)")
    s.add_argument("--bearer-file", help="게이트웨이 Bearer 토큰 파일")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("eval", help="L3 에이전트 평가 (claude -p)")
    s.add_argument("eval_file"), s.add_argument("--url", required=True, action="append")
    s.add_argument("--only", action="append"), s.add_argument("--model")
    s.add_argument("--bearer-file", help="게이트웨이 Bearer 토큰 파일")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("contract", help="인터페이스 계약서(HTML)")
    s.add_argument("spec"), s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_contract)

    s = sub.add_parser("drift", help="소스 변경 영향 분석")
    s.add_argument("lock"), s.add_argument("--source", required=True)
    s.set_defaults(fn=cmd_drift)

    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
