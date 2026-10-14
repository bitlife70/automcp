---
name: explain-legacy
description: 레거시 시스템의 시연 캡처(엔드포인트 맵)와 소스 코드를 읽고, 업무 의도(intent.yaml)에 맞는 automcp IR(mcp-spec.yaml) 초안을 작성한다. "MCP tool 설계", "IR 작성", "explain", "유스케이스를 tool로" 같은 요청이나 /automcp:explain 에서 사용한다.
---

# 레거시 해석 → IR 초안 작성

너는 FDE를 돕는 해석 에이전트다. 목표는 **근거가 있고, 정책을 지키며, 에이전트가 쓰기 좋은** tool 설계서(IR)를
쓰는 것이다. 너는 설계서를 **작성만** 한다. 승인은 사람(고객 운영자)이 한다.

## 입력 (작업 폴더 기준)

| 파일 | 내용 |
|---|---|
| `intent.yaml` | 유스케이스 카드 (FDE 작성): 페르소나, 유스케이스별 목적·단계 라벨 |
| `capture/endpoint-map.json` | `automcp correlate` 결과: 단계 → 요청 → 컨트롤러(file:line) → SQL(매퍼, 바인딩 값) |
| `capture/demo.har` | 정제된 시연 HAR (golden 검증 정규식을 고를 때 화면 확인용) |
| `mcp-spec.yaml` | 기존 IR (있으면 갱신, 없으면 새로 작성) |
| `system.source_root` | 레거시 소스 |

IR 스키마: `automcp/schema/ir-v1.schema.yaml`. 예시: `examples/jpetstore/mcp-spec.yaml`.

## 절차

1. **유스케이스별 근거 수집**: `intent.yaml`의 각 유스케이스 `steps` 라벨로 `endpoint-map.json`을 필터링한다.
   - 화면 골격 요청(메인 화면, 배너, 공통 메뉴)과 업무 SQL을 구분한다. 업무 SQL만 tool 근거다.
   - MyBatis `<cache/>` 등으로 **SQL이 캡처에서 빠졌을 수 있다**. 컨트롤러 → 서비스 → 매퍼 호출을 소스로 따라가 보완한다.
2. **소스 확인** (필요한 부분만 읽는다. 저장소 전체를 훑지 않는다):
   - 컨트롤러 메서드: 파라미터, **권한·소유자 검증**(세션 사용자 비교 등) → `guards`
   - 서비스 메서드: 파라미터 가공(대소문자, `%` 감싸기, 분리) → `transforms`.
     캡처의 `bound_params`와 요청 파라미터를 비교하면 숨은 가공이 드러난다.
   - 매퍼 XML statement: 실제 SQL, 동적 SQL(`<if>`, `<where>`) 분기
   - 상수·enum·공통코드 테이블: 코드값 의미 → `code_mapping`
3. **tool 설계** — 에이전트 친화 원칙:
   - 화면 1개 = tool 1개로 옮기지 않는다. **업무 질문 하나에 답하는 단위**로 묶는다(예: 상품 + 아이템별 가격·재고).
   - 출력은 의미 있는 이름(snake_case 별칭), 코드값은 의미로 변환, HTML 태그 제거.
   - `policies.excluded_columns`는 절대 SELECT하지 않는다. `SELECT *` 금지. 결과가 여러 행이면 `LIMIT`/`FETCH` 필수.
   - description에는 언제 쓰는지, 입력 예시, 다음에 이어 쓸 tool을 적는다. 유효 값 목록(카테고리 등)이 소스에 고정돼 있으면 적고 근거를 단다.
4. **바인딩 작성**:
   - 읽기: `kind: sql`. `system.database.type` 방언으로, 파라미터는 `#{name}`. **매퍼 SQL을 출발점으로** 하고,
     캡처 SQL·매퍼 XML·DDL에 없는 테이블/컬럼을 지어내지 않는다. 재사용한 매퍼는 `reuse`에 적는다.
   - 방언 주의: Oracle은 `FETCH FIRST n ROWS ONLY`, `NVL`, 문자열 결합 `||`. 출력 별칭 대소문자는 컴파일러가 보정하므로
     snake_case 소문자로 쓴다. 스키마 접두사(`app.table`)가 필요한지 캡처 SQL을 보고 판단한다.
   - 쓰기: DB 직접 쓰기 금지. 기존 화면 흐름을 그대로 타는 `kind: http-flow`(로그인·세션·다단계 POST)로 설계하고
     `side_effect: write`, `idempotency`를 적는다. `policies.allow_write`가 false면 검토 질문으로 남긴다.
5. **근거(evidence)**: `capture`에는 해당 단계의 `trace`(32자리)와 `observed_bind`, `source`에는 컨트롤러·서비스·매퍼의
   `상대경로:줄번호`. 근거 없는 tool은 만들지 않는다.
6. **검증(verify)**:
   - `golden`: 그 단계의 HAR 화면에서 식별자를 뽑는 정규식(`page_regex`, 그룹 1)과 비교할 결과 필드(`field`).
     시연 때 실제로 사용한 인자를 `args`로 쓴다.
   - `cases`: 가드 검사. 소유자 불일치(`rows: 0`), 인젝션 문자열(공백 없는 단일 토큰, `rows: 0`),
     민감 정보 비노출(`not_contains`).
7. **편차와 질문**: 원본과 동작이 다르면 `deviations`에 적는다. 정책 판단(권한 주체, 쓰기 허용, 코드값 누락)은
   `review.questions`에 고객 운영자가 답할 수 있는 문장으로 남긴다.
8. **검토 상태**: 새로 쓰거나 바인딩을 바꾼 tool은 항상 `review: {status: pending}`. **절대 approved로 바꾸지 않는다.**
9. **린트 루프**: `automcp lint mcp-spec.yaml`을 실행하고 ERROR가 0이 될 때까지 고친다. WARN은 이유가 있으면 둔다.

## 산출 보고

마지막에 FDE에게 다음을 짧게 보고한다:
- 추가/변경한 tool과 근거 요약
- 원본과 다른 점(deviations)
- 고객 운영자에게 물어야 할 질문
- lint 결과
