---
description: 승인된 IR을 lint → compile 하고, 실행 중인 MCP 서버를 verify 한다
argument-hint: <workspace 폴더> [MCP URL]
---

1. `automcp lint $1/mcp-spec.yaml` — ERROR가 있으면 멈추고 원인을 보고한다.
2. `automcp compile $1/mcp-spec.yaml --out $1/build` — 승인된 tool만 포함된다. 제외된 tool과 사유를 보고한다.
3. MCP URL(`$2`, 기본 `http://localhost:5000/mcp/<agent.name>`)의 서버가 새 `tools.yaml`을 읽도록 재시작이 필요하면
   명령을 안내한다(예: `docker compose restart toolbox`).
4. `automcp verify $1/mcp-spec.yaml --url <URL>` — 실패 항목은 golden(데이터 불일치)과 guard(보안)로 나눠 원인을 분석하고,
   IR 수정이 필요하면 무엇을 바꿔야 하는지 제안한다(직접 approved로 바꾸지 않는다).
