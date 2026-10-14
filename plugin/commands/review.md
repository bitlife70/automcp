---
description: 운영자 검토용 인터페이스 계약서(HTML)를 만들고 승인 결과를 IR에 반영한다
argument-hint: <workspace 폴더>
---

1. `automcp contract $1/mcp-spec.yaml --out $1/build/contract.html`로 계약서를 만든다.
2. FDE에게 계약서를 고객 운영자와 검토하라고 안내하고, 검토 질문(`review.questions`) 목록을 보여 준다.
3. FDE가 tool별 승인/반려와 답변을 알려 주면 그대로 IR의 `review`(`status`, `by`, `at`, `comment`)와
   `review.questions[].answer`에 기록한다. **FDE가 명시적으로 말하지 않은 tool은 승인 처리하지 않는다.**
4. 답변 때문에 설계가 바뀌어야 하면(권한 주체, 코드값 등) 해당 tool을 수정하고 다시 `pending`으로 둔다.
