# automcp 0단계 스파이크 — jpetstore + PostgreSQL

"운영자가 업무를 시연하면 MCP 서버가 된다"는 흐름을 레거시 샘플 앱(jpetstore: Spring MVC + JSP + MyBatis)으로
끝까지 통과시킨 기술 검증이다.

```
시연(Playwright) ──▶ 캡처(HAR + OTel 트레이스) ──▶ 상관분석(엔드포인트 맵)
      ──▶ IR(mcp-spec.yaml) ──▶ tools.yaml ──▶ MCP Toolbox ──▶ 검증(golden replay + guard)
```

## 실행

```bash
git clone --depth 1 https://github.com/mybatis/jpetstore-6.git targets/jpetstore-6   # 저장소 루트에서
cd spike
docker compose up -d --build                     # db, otel-collector, jpetstore, toolbox
cd scripts && npm install && npx playwright install chromium && cd ..
node scripts/demo.mjs                            # 업무 시연 → capture/demo.har, capture/traces.jsonl
python -I scripts/correlate.py capture/traces.jsonl ../targets/jpetstore-6 capture   # → capture/endpoint-map.md
../.venv/Scripts/python scripts/verify.py ir/mcp-spec.yaml capture/demo.har http://localhost:5000/mcp/cs-agent
```

| 구성 | 위치 | 역할 |
|---|---|---|
| `jpetstore/` | Dockerfile, applicationContext.xml | 레거시 WAS 재현. 원본 대비 변경은 DataSource(HSQLDB→PG) 하나 |
| `db/` | 02a-pg-compat.sql, 03-mcp-reader.sql | PG 호환 보정, MCP 전용 최소권한 계정(카드 컬럼 권한 제외) |
| `otel/collector.yaml` | | 캡처 키트 수집기 (파일 저장만, 외부 전송 없음) |
| `scripts/demo.mjs` | | 운영자 시연 대역. 단계마다 `x-automcp-step` 라벨 |
| `scripts/correlate.py` | | 트레이스 ↔ 컨트롤러(file:line) ↔ SQL ↔ 매퍼 statement 연결, 민감값 마스킹 |
| `ir/mcp-spec.yaml` | | IR v0. 근거·변환·가드·편차·검증·검토 질문 포함 |
| `toolbox/tools.yaml` | | IR을 수작업 컴파일한 MCP 서버 설정 (서버 코드 없음) |
| `scripts/verify.py` | | MCP 프로토콜로 호출해 캡처와 대조 + 보안 가드 검사 |

## 결과

- **상관분석**: 시연 14개 요청, SQL 18개 중 **18개를 MyBatis 매퍼 statement에 자동 매칭**. 컨트롤러 메서드 위치도 자동.
  운영자 측 작업은 JVM 옵션 1줄과 환경변수뿐이고 앱 코드 수정은 0.
- **검증**: `verify.py` **10/10 통과**
  - golden replay 4건: tool 결과 = 시연 화면(HAR)의 상품/아이템/주문 ID, 주문 금액
  - guard 6건: 소유자 불일치 조회 차단, SQL 인젝션 무력화 2건, 인젝션 후 테이블 정상, 결제수단 비노출, tool 목록 일치
  - DB 단: `mcp_reader`로 `creditcard` 조회 시 `permission denied`

## 발견 사항 → 계획 반영

| # | 발견 | 반영 |
|---|---|---|
| 1 | 캡처된 바인딩 값(`%fish%`)이 서비스 레이어의 숨은 변환 규칙을 드러냄. 소스만 읽었다면 놓치기 쉬움 | IR에 `transforms` 필드. 캡처를 1순위 근거로 유지 |
| 2 | 캡처에 **비밀번호·카드번호가 평문**으로 남음 | 마스킹 필수. 현재는 상관분석기에서 처리 → 수집기 redaction 단계로 이동 |
| 3 | jpetstore는 JSP가 **HTML을 반환**하므로 Toolbox `http` tool로 감싸면 HTML이 그대로 나옴 | 읽기는 SQL 바인딩(기존 매퍼 SQL 재사용)이 현실적. HTML 화면 감싸기는 Camel 경로에서 검증 |
| 4 | 주문 생성 1건이 **세션 상태를 쓰는 POST 3회**(폼 → 제출 → 확인)로 이루어짐 | 쓰기 tool은 단일 HTTP 호출로 만들 수 없음 → Camel 다단계 라우트 PoC 필요 |
| 5 | 원본은 "본인 주문만 조회". Toolbox의 인증 파라미터는 일반 MCP 클라이언트에서 지원되지 않음 | 페르소나(상담 직원 권한)를 IR에 명시하고 검토 질문(Q1)으로 승인. 사용자 신원 주입은 게이트웨이 과제 |
| 6 | 컨트롤러의 소유자 검증을 SQL 조건으로 재현 가능 | IR에 `guards` 필드 |
| 7 | DB 방언 차이(DATE→LocalDateTime)가 **실행해 봐야** 드러남 | 캡처 기반 실행 검증의 가치 확인 |
| 8 | 테스트 데이터를 따로 만들지 않고 HAR만으로 golden 검증이 가능 | 검증 하네스의 기본 방식으로 채택 |

## 판정

- **읽기 경로 (MCP Toolbox + SQL 바인딩): Go**
- **쓰기 경로, HTML 화면 감싸기, EUC-KR: 미검증** → 다음 스파이크(Camel)

## 다음 단계 (1단계)

1. IR → tools.yaml **컴파일러** (현재 수작업 부분)
2. 엔드포인트 맵 → IR 초안을 만드는 **해석 에이전트** (Claude Code skill)
3. 수집기 단계의 **민감값 redaction**
4. Camel `camel-mcp-server`로 쓰기(주문 생성) 다단계 라우트 PoC
