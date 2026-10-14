---
description: 레거시 소스 변경이 생성된 MCP tool에 미치는 영향을 분석한다
argument-hint: <workspace 폴더> <새 소스 경로>
---

`automcp drift $1/build/automcp.lock.json --source $2`를 실행한다.

- BREAKING(매퍼 SQL 변경·삭제): 해당 tool의 바인딩을 새 SQL 기준으로 다시 검토하고, 필요하면 시연을 다시 캡처하도록 안내한다.
  수정한 tool은 `review.status: pending`으로 되돌린다.
- MOVED: 근거 줄 번호만 갱신한다.
- CHANGED: 근거 줄의 의미가 바뀌었는지 소스를 읽고 판단한다.
결과를 tool별 조치 목록으로 보고한다.
