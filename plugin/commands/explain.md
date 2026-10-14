---
description: 엔드포인트 맵과 소스를 해석해 IR(mcp-spec.yaml) 초안을 작성·갱신한다
argument-hint: <workspace 폴더> [유스케이스 ID...]
---

`explain-legacy` skill의 절차를 따라 작업 폴더 `$1`의 `intent.yaml`, `capture/endpoint-map.json`,
소스를 읽고 `$1/mcp-spec.yaml`을 작성하거나 갱신한다. 유스케이스 ID가 주어지면 그 유스케이스만 다룬다: $ARGUMENTS

끝나면 `automcp lint $1/mcp-spec.yaml`의 ERROR가 0인 상태로 보고한다. 모든 신규·변경 tool은 `review.status: pending`이다.
