# automcp

레거시 시스템 운영자가 API나 MCP를 직접 개발하지 않아도, **업무 시연 캡처와 소스**로부터
에이전트용 MCP 서버를 설계·생성·검증하는 FDE 도구입니다.

```
의도 카드 ─▶ 시연 캡처 ─▶ 상관분석 ─▶ 해석(IR) ─▶ 검토·승인 ─▶ 컴파일 ─▶ 검증·평가 ─▶ 배포
intent.yaml  recorder     correlate    explain     contract     compile    verify/eval   gateway
             +OTel agent  (결정적)     (Claude)    (운영자)     (결정적)
```

- **코드가 아니라 설정을 생성합니다.** 읽기는 MCP Toolbox(`tools.yaml`), 쓰기·화면 흐름은 automcp flow 런타임(`flows.yaml`)이 실행합니다.
- **LLM은 설계만 합니다.** 해석 에이전트가 IR을 쓰고, 린터가 환각(없는 매퍼·파일·trace)과 정책 위반(민감 컬럼, `SELECT *`, DML)을 차단합니다.
- **사람이 승인한 tool만 배포됩니다.** 운영자는 코드 대신 인터페이스 계약서(HTML)를 검토합니다.
- **시연 캡처가 곧 테스트입니다.** 시연 화면(HAR)과 tool 결과를 비교하고(golden), 실제 Claude 에이전트로 업무 질문을 평가합니다(eval).

## 구성

| 경로 | 내용 |
|---|---|
| `automcp/` | Python 패키지·CLI: sanitize-har, correlate, lint, compile, verify, eval, contract, drift |
| `automcp/runtime/` | http-flow 런타임 (레거시 화면 흐름 → MCP tool, 세션·폼 기본값·문자셋·멱등성) |
| `automcp/schema/ir-v1.schema.yaml` | IR 스키마 |
| `plugin/` | Claude Code 플러그인: `/automcp:capture`, `explain`, `review`, `build`, `drift` + `explain-legacy` skill |
| `recorder/` | 시연 녹화기 (대화형 / 시나리오) |
| `capture-kit/` | 고객사 설치용 캡처 키트 (수집기 설정 + 운영자 가이드) |
| `docker/` | flow 런타임 이미지 |
| `examples/jpetstore/` | 예제 작업 폴더: intent, IR, 시나리오, eval, 생성물(build/) |
| `examples/jpetstore-oracle/` | Oracle 방언 예제 |
| `spike/` | 검증 환경: 레거시 WAS(jpetstore) + PostgreSQL/Oracle + 수집기 + Toolbox + flow 런타임 + 게이트웨이 |
| `docs/pilot-playbook.md` | 현장 파일럿 플레이북 |
| `tests/` | 단위 테스트 (린터 부정 사례, 컴파일러, 런타임, drift, HAR 정제) |

## 빠른 시작 (예제 재현)

처음 사용한다면 단계별 안내 [docs/getting-started.md](docs/getting-started.md)를 먼저 보세요.

```bash
git clone https://github.com/bitlife70/automcp.git && cd automcp
git clone --depth 1 https://github.com/mybatis/jpetstore-6.git targets/jpetstore-6
python -m venv .venv && .venv/Scripts/pip install -e ".[dev,runtime]"   # Windows. macOS/Linux는 .venv/bin
(cd recorder && npm install && npx playwright install chromium)

cd spike && docker compose up -d --build && cd ..                     # 레거시 + 런타임 + 게이트웨이
node recorder/record.mjs --base-url http://localhost:8080/jpetstore \
     --out examples/jpetstore/capture/raw --scenario examples/jpetstore/scenario.mjs
automcp sanitize-har examples/jpetstore/capture/raw/demo.raw.har examples/jpetstore/capture/demo.har
automcp correlate examples/jpetstore/capture/raw/traces.jsonl --source targets/jpetstore-6 --out examples/jpetstore/capture
automcp lint examples/jpetstore/mcp-spec.yaml
automcp compile examples/jpetstore/mcp-spec.yaml --out examples/jpetstore/build --allow-pending   # 예제는 미승인 상태
(cd spike && docker compose restart toolbox flow-runtime)
automcp verify examples/jpetstore/mcp-spec.yaml --url http://localhost:5000/mcp/cs-agent --url http://localhost:5100/mcp/
python spike/gateway/register.py                                      # 게이트웨이에 등록 → 단일 엔드포인트
automcp eval examples/jpetstore/eval.yaml --url "$(cat spike/gateway/.server-url)" --bearer-file spike/gateway/.token --model sonnet
```

> 시연 캡처의 trace ID는 실행마다 달라집니다. 다시 녹화했다면 `/automcp:explain`으로 IR 근거를 갱신하세요.

Claude Code 플러그인 설치: Claude Code에서 `/plugin marketplace add <이 저장소 경로>` → `/plugin install automcp@automcp-local`.

## 검증 현황 (jpetstore 예제)

| 항목 | 결과 |
|---|---|
| 단위 테스트 | 31 통과 |
| 상관분석 | SQL 19/19 매퍼 매칭 |
| verify (PostgreSQL, Toolbox + flow 런타임, 게이트웨이 경유 포함) | 15/15 |
| verify (Oracle 23 Free) | 5/5 |
| eval (Claude 에이전트, 업무 질문 6개) | 6/6 |
| 게이트웨이 인증 | 토큰 없음·위조 토큰 401 |

## 설계 원칙

1. 바인딩 우선순위: 기존 화면·API 흐름 > 저장 프로시저 > 기존 매퍼 SQL 재사용(읽기). **DB 직접 쓰기 금지.**
2. 모든 tool은 캡처 근거(trace)와 소스 근거(file:line)를 가진다.
3. 결제정보·자격증명은 에이전트를 거치지 않는다(화면 기본값 제출, 런타임 비밀 주입).
4. 소스가 바뀌면 `automcp drift`가 영향받는 tool을 찾는다(매퍼 SQL 지문, 근거 줄 지문).
