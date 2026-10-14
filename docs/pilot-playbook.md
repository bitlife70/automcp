# 현장 파일럿 플레이북 (FDE용)

목표: 고객사 레거시 시스템 1개를 **운영자 개발 공수 없이** 에이전트가 쓸 수 있는 MCP로 연결하고,
"소스·시연 → 검증된 MCP 배포" 리드타임을 측정한다. 목표치는 **시스템당 FDE 2~3일**이다.

## 0. 착수 전 (D-10 ~ D-1)

### 계약·동의
- [ ] 분석 범위 합의서: 대상 시스템, 소스 열람 범위, **캡처 데이터 반출 금지**(내부망 보관), 결과물 소유권
- [ ] 패키지 소프트웨어면 벤더 라이선스에서 역분석·연동 조항 확인
      (참고: 저작권법 제101조의4는 정당한 이용자가 호환에 필요한 범위에서 역분석을 허용. 법률 자문 아님)
- [ ] LLM 사용 방식 합의: 소스·캡처를 어떤 LLM 엔드포인트로 보내는지
      (Claude API / 클라우드 리전 엔드포인트 / 사내 LLM). 망분리 정책 확인
- [ ] 쓰기 tool 허용 여부와 승인 체계(누가 계약서에 서명하는가)

### 환경
- [ ] 개발 또는 스테이징 WAS 접근, 재시작 권한(캡처 키트 설치용)
- [ ] 테스트 계정, 테스트 데이터(운영 데이터 복제본이면 마스킹 여부 확인)
- [ ] 소스 저장소 열람 권한(전체가 아니라 대상 모듈만으로도 가능)
- [ ] DB: MCP 전용 계정 생성 권한 → 최소권한 계정 `mcp_reader` (Oracle은 뷰로 제한, `capture-kit/README.md` 7절)
- [ ] FDE 작업 PC: Python 3.11+, Node 20+, Docker, Claude Code + automcp 플러그인

### 유스케이스 카드 (`intent.yaml`)
현업 인터뷰 30분으로 3~5개를 작성한다. **"에이전트가 받을 질문"** 단위로 쓰고, 각 유스케이스에 시연 단계 라벨을 정한다.
쓰기 유스케이스는 첫 파일럿에 최대 1개.

## 1. 일정 (시스템 1개 기준)

| 일차 | 오전 | 오후 | 산출물 |
|---|---|---|---|
| **1일차** | 캡처 키트 설치(운영자 30분), 수집기 기동 | 운영자 시연 녹화(유스케이스당 10~30분) → 정제 → 상관분석 | `capture/endpoint-map.md` |
| **2일차** | `/automcp:explain` → IR 초안, lint 0 | `/automcp:review` → 계약서 → **운영자 검토 미팅(1시간)** | `build/contract.html`, 승인된 IR |
| **3일차** | `/automcp:build` → compile → 배포 → verify | 에이전트 평가(eval) → 결과 보고 | 배포된 MCP, 검증·평가 리포트 |

운영자 투입 시간: 설치 30분 + 시연 1~2시간 + 검토 1시간 = **약 3시간, 코딩 0**.

## 2. 단계별 명령

```bash
# 작업 폴더: workspace/<시스템명>/ (intent.yaml, mcp-spec.yaml, capture/, build/)
node recorder/record.mjs --base-url <URL> --out workspace/<sys>/capture/raw
automcp sanitize-har workspace/<sys>/capture/raw/demo.raw.har workspace/<sys>/capture/demo.har
automcp correlate workspace/<sys>/capture/raw/traces.jsonl --source <소스> --out workspace/<sys>/capture
# Claude Code: /automcp:explain workspace/<sys>   → mcp-spec.yaml (모든 tool pending)
automcp lint workspace/<sys>/mcp-spec.yaml
automcp contract workspace/<sys>/mcp-spec.yaml --out workspace/<sys>/build/contract.html
# 운영자 검토 → /automcp:review 로 승인 결과 기록
automcp compile workspace/<sys>/mcp-spec.yaml --out workspace/<sys>/build          # 승인된 tool만
automcp verify workspace/<sys>/mcp-spec.yaml --url <MCP URL> [--bearer-file ...]
automcp eval workspace/<sys>/eval.yaml --url <MCP URL> --model sonnet
```

## 3. 배포 구성

```
에이전트 ──(Bearer)──▶ MCP 게이트웨이(ContextForge) ─┬─▶ MCP Toolbox  (tools.yaml)  ──▶ 레거시 DB (mcp_reader)
                                                    └─▶ flow 런타임  (flows.yaml)  ──▶ 레거시 WAS 화면 흐름
```

- 생성물은 설정 파일뿐이다(`tools.yaml`, `flows.yaml`). 운영자가 읽고 고칠 수 있다.
- 비밀값(DB 계정, 위임 계정, JWT 키)은 환경변수나 Vault로만 주입한다. IR·생성물에는 `${ENV}` 참조만 남는다.
- 게이트웨이: 토큰 없는 요청 401, 에이전트별 가상 서버, tool 호출 감사. 다중 노드는 Redis 캐시 필요.

## 4. Go / No-go 기준

| 항목 | 기준 |
|---|---|
| lint | 오류 0 |
| verify | golden·guard 100% 통과 |
| eval | 시나리오 90% 이상 통과, **보안 시나리오(권한·민감정보) 100%** |
| 검토 | 모든 배포 tool `approved`, 검토 질문 답변 완료 |
| 운영 | 장애 시 게이트웨이에서 가상 서버 비활성화로 즉시 차단 가능 |

## 5. 측정 지표 (파일럿 보고서에 기록)

| 지표 | jpetstore 기준값 (spike) |
|---|---|
| 시연 → 엔드포인트 맵 SQL 매칭률 | 19/19 (100%) |
| IR 초안 lint 오류(최초) | 0 |
| verify 통과율 | 15/15 (PostgreSQL), 5/5 (Oracle) |
| eval 통과율 / 시나리오당 비용 | 6/6, Sonnet 약 $0.07 |
| 운영자 투입 시간 | (측정) |
| 소스·시연 수령 → 배포 리드타임 | (측정) |

## 6. 자주 만나는 문제

| 증상 | 원인·대응 |
|---|---|
| 캡처에 SQL이 없음 | MyBatis `<cache/>` 등 캐시 적중. WAS 재시작 직후 시연하거나 소스로 보완(explain skill이 처리) |
| 매퍼 미매칭 SQL | 동적 SQL(`<if>`)이나 매퍼 밖 JDBC. 엔드포인트 맵의 SQL 원문으로 직접 근거를 단다 |
| Oracle에서 결과 필드가 비어 있음 | 대문자 별칭 문제 → 컴파일러가 자동 보정. 수동 SQL이라면 `AS "field"` |
| 응답 문자 깨짐 | `system.http.charset: MS949`(또는 EUC-KR) 지정 |
| 화면 흐름 tool이 "기대 문구 없음" | 화면 문구가 바뀌었거나 세션 만료. 오류 메시지의 화면 내용을 보고 `expect.contains` 조정 |
| 에이전트가 코드값을 그대로 말함 | `code_mapping` 누락 → 운영자에게 코드표 요청(검토 질문) |

## 7. 아직 지원하지 않는 것 (로드맵)

- TCP 고정길이 전문, MQ: Apache Camel 어댑터(`camel-mcp-server`)를 http-flow와 같은 IR 바인딩 종류로 추가 예정
- 화면 자동화(Playwright/pywinauto) 바인딩: 인터페이스가 전혀 없는 시스템용, 읽기 전용부터
- 사용자 신원 전파: 게이트웨이 토큰의 사용자 → 레거시 권한 매핑(현재는 페르소나 단위 권한)
