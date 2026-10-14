# 캡처 키트 설치 가이드 (고객사 운영자용)

이 키트는 **개발 또는 스테이징 서버**에서 업무 시연을 하는 동안 "어떤 화면 요청이 어떤 SQL을 실행했는지"를 기록합니다.
**애플리케이션 코드는 수정하지 않습니다.** 설정만 추가하며, 작업이 끝나면 설정을 지우는 것으로 원상 복구됩니다.

> ⚠️ 운영(Production) 서버에는 설치하지 마세요. 시연은 테스트 계정과 테스트 데이터로 진행합니다.

## 1. 구성 요소

| 구성 | 위치 | 하는 일 |
|---|---|---|
| OTel Java 에이전트 | WAS JVM 옵션 | 요청 URL, 컨트롤러, 실행 SQL(바인딩 값 포함)을 트레이스로 기록 |
| 수집기 | 같은 망의 서버 1대 (Docker 또는 단일 바이너리) | 트레이스를 **파일로만** 저장. 민감값(비밀번호·카드번호·주민번호)은 저장 전에 제거 |
| 녹화기 | 시연자 PC | 브라우저 조작을 HAR로 녹화하고 단계 이름을 붙임 |

외부 인터넷으로 나가는 통신은 없습니다.

## 2. 수집기 실행

```bash
docker run -d --name automcp-collector -p 4318:4318 \
  -v $(pwd)/otel-collector.yaml:/etc/otelcol/collector.yaml:ro \
  -v $(pwd)/capture:/capture \
  otel/opentelemetry-collector-contrib:0.160.0 --config=/etc/otelcol/collector.yaml
```

Docker를 쓸 수 없으면 같은 버전의 `otelcol-contrib` 바이너리를 `--config otel-collector.yaml`로 실행합니다.
결과는 `capture/traces.jsonl`에 쌓입니다.

## 3. WAS에 에이전트 붙이기 (JVM 옵션 한 줄 + 환경변수)

`opentelemetry-javaagent.jar`(v2.31.1)를 서버에 복사한 뒤, WAS별로 아래 위치에 JVM 옵션을 추가합니다.

| WAS | 설정 위치 |
|---|---|
| Tomcat | `bin/setenv.sh`의 `CATALINA_OPTS="$CATALINA_OPTS -javaagent:/opt/otel/opentelemetry-javaagent.jar"` |
| JEUS | `domain.xml` 서버 `jvm-config`의 `jvm-option` |
| WebLogic | `setDomainEnv.sh`의 `JAVA_OPTIONS` |
| WebSphere | 관리 콘솔 → 서버 → Java 및 프로세스 관리 → 일반 JVM 인수 |
| Spring Boot (jar) | `java -javaagent:... -jar app.jar` |

환경변수(또는 같은 이름의 `-D` 시스템 프로퍼티, 예: `-Dotel.service.name=...`):

```bash
OTEL_SERVICE_NAME=<시스템명>
OTEL_EXPORTER_OTLP_ENDPOINT=http://<수집기 주소>:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_METRICS_EXPORTER=none
OTEL_LOGS_EXPORTER=none
OTEL_INSTRUMENTATION_JDBC_EXPERIMENTAL_CAPTURE_QUERY_PARAMETERS=true
OTEL_INSTRUMENTATION_COMMON_EXPERIMENTAL_CONTROLLER_TELEMETRY_ENABLED=true
OTEL_INSTRUMENTATION_HTTP_SERVER_CAPTURE_REQUEST_HEADERS=x-automcp-step
# 화면 요청 파라미터 중 기록할 이름(쉼표 구분). 비밀번호 등은 넣지 않는다.
OTEL_INSTRUMENTATION_SERVLET_EXPERIMENTAL_REQUEST_PARAMETERS_INCLUDED=<파라미터1>,<파라미터2>
```

WAS를 재시작한 뒤 로그에 `opentelemetry-javaagent - version: 2.31.1`이 보이면 됩니다.
**작업 종료 후** 위 JVM 옵션과 환경변수를 지우고 재시작하면 원상 복구됩니다.

## 4. 업무 시연 녹화

시연자 PC(Node.js 20 이상)에서:

```bash
cd recorder && npm install && npx playwright install chromium
node record.mjs --base-url http://<개발 WAS>/<컨텍스트> --out ../workspace/capture/raw
```

브라우저가 열리면 터미널에 **단계 이름**(예: `UC-1/주문조회`)을 입력하고 해당 업무를 수행합니다.
다음 업무로 넘어갈 때마다 새 단계 이름을 입력하고, 끝나면 `q`를 입력합니다.
단계 이름은 FDE가 준비한 유스케이스 카드(`intent.yaml`)의 `steps`와 같게 씁니다.

## 5. 결과물 취급

| 파일 | 내용 | 반출 |
|---|---|---|
| `capture/raw/traces.jsonl` | 수집기 원본 (민감값 1차 제거됨) | **내부망 보관** |
| `capture/raw/demo.raw.har` | 녹화 원본 (쿠키·입력값 포함) | **반출 금지**, 정제 후 삭제 |
| `capture/demo.har` | `automcp sanitize-har`로 정제한 HAR | 분석용 |
| `capture/endpoint-map.json` | 상관분석 결과 (민감 바인딩 값 제거) | 분석용 |

## 6. 소스가 없거나 Java가 아닌 시스템

- **PowerBuilder, Delphi 등 C/S 시스템**: WAS 에이전트 대신 DB 측에서 SQL을 수집합니다.
  - Oracle: 시연 전후로 `V$SQL`(`LAST_ACTIVE_TIME`, `PARSING_SCHEMA_NAME`)을 조회하거나 Unified Auditing 정책 사용
  - SQL Server: Extended Events 세션(`sql_statement_completed`)
- **.NET**: OpenTelemetry .NET 자동 계측(`OTEL_DOTNET_AUTO_*`)으로 같은 형태의 트레이스를 얻을 수 있습니다.

## 7. Oracle 운영 DB 주의 사항

Oracle은 **SELECT 권한을 컬럼 단위로 줄 수 없습니다.** 에이전트에 보이면 안 되는 컬럼(카드번호, 원가 등)이 있는 테이블은
그 컬럼을 뺀 **전용 뷰**를 만들고, MCP 전용 계정(`mcp_reader`)에는 뷰에 대한 SELECT만 부여하세요.

```sql
CREATE VIEW app.v_mcp_item AS SELECT itemid, productid, listprice, status, attr1, attr2 FROM app.item;
GRANT SELECT ON app.v_mcp_item TO mcp_reader;
```
