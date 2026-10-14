# 처음 사용하기 — 내 레거시 폴더로 실험하는 방법

흐름은 **① 예제로 도구가 정상인지 확인(약 20분) → ② 내 폴더의 시스템에 적용** 순서입니다.
아래에서 실험할 폴더는 `D:\legacy\myapp`, 시스템 이름은 `myapp`으로 가정합니다. 실제 경로로 바꿔 쓰세요.
명령은 Windows PowerShell 기준입니다.

## 0. 알아 둘 것

이 도구는 **"레거시 시스템을 한 번 시연하면 그 업무를 하는 MCP tool이 생기는 것"**입니다. 폴더에 무엇이 있느냐에 따라 범위가 다릅니다.

| 폴더에 있는 것 | 가능한 실험 |
|---|---|
| **소스 + 실행 가능한 개발 환경**(WAS·DB) | 전체: 시연 → 캡처 → 설계 → 생성 → 검증 → 에이전트 평가 |
| 소스 + DB만 (앱 실행 불가) | 소스로 설계 → 생성 → DB 기준 검증 (시연 화면 비교는 불가) |
| 소스만 | 설계서(IR) 초안과 린트까지 |

현재 자동 분석이 잘 되는 대상은 **Java(Spring 등) + MyBatis XML 매퍼**입니다. 다른 스택은 수작업 비중이 커집니다.

## 1. 설치 (최초 1회)

준비물: Python 3.11+, Node.js 20+, Docker Desktop(실행 중), Claude Code, git

```powershell
git clone https://github.com/bitlife70/automcp.git
cd automcp
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,runtime]"
automcp --help
cd recorder; npm install; npx playwright install chromium; cd ..
```

## 2. 예제로 도구 정상 여부 확인 (약 20분)

여기서 실패하면 도구나 설치 문제이고, 여기서는 되는데 내 폴더에서 안 되면 대상 시스템의 특성 때문입니다.

```powershell
git clone --depth 1 https://github.com/mybatis/jpetstore-6.git targets/jpetstore-6

# ① 예제 레거시 환경을 처음 상태로 띄움 (DB, 레거시 앱, 수집기, 조회·쓰기 런타임)
cd spike; docker compose down -v; docker compose up -d --build db otel-collector jpetstore toolbox flow-runtime; cd ..

# ② 업무 시연 자동 재생 → 빈 DB에 주문 데이터가 생김 (결과는 임시 폴더)
node recorder/record.mjs --base-url http://localhost:8080/jpetstore --out tmp/capture --scenario examples/jpetstore/scenario.mjs

# ③ 설계서 검사 → MCP 설정 생성 → 런타임 반영
automcp lint examples/jpetstore/mcp-spec.yaml
automcp compile examples/jpetstore/mcp-spec.yaml --out examples/jpetstore/build --allow-pending
cd spike; docker compose restart toolbox flow-runtime; cd ..

# ④ 동작 검증
automcp verify examples/jpetstore/mcp-spec.yaml --url http://localhost:5000/mcp/cs-agent --url http://localhost:5100/mcp/
```

**판정**: lint `오류 0`, verify `15/15 통과`면 정상입니다.

> 게이트웨이(`gateway` 서비스)는 비밀값 파일 `spike/gateway/.env`가 필요합니다(git 제외).
> 필요한 키는 `JWT_SECRET_KEY`, `AUTH_ENCRYPTION_SECRET`, `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD`,
> `DEFAULT_USER_PASSWORD`(12자 이상)이며, 만든 뒤 `python spike/gateway/register.py`로 등록합니다.

## 3. 실제 에이전트로 써 보기 (선택)

```powershell
claude --plugin-dir .\plugin
```

프로젝트 MCP 서버(`jpetstore-cs`, `jpetstore-cs-write`) 승인 후 "강아지 상품 뭐 있어? 가격대도 알려줘"처럼 물어봅니다.

## 4. 내 폴더가 대상에 맞는지 진단

```powershell
python -c "from automcp.correlate import index_mappers as f; m=f(r'D:\legacy\myapp'); print(len(m),'개 SQL'); [print(' ',x['id'],x['file']) for x in m[:10]]"
```

| 결과 | 의미 |
|---|---|
| SQL 수십 개 이상 | MyBatis 매퍼 인식 성공 → 전체 흐름 가능 |
| 0개 | MyBatis가 아님(JPA, 직접 JDBC 등). 시연 캡처의 SQL 원문으로 진행 가능하나 수작업 증가 |

컨트롤러 위치 자동 탐색은 `src/main/java/...` 구조를 가정합니다.

## 5. 작업 폴더 만들기

```powershell
mkdir workspace\myapp\capture\raw
copy examples\jpetstore\intent.yaml workspace\myapp\intent.yaml
```

`intent.yaml`에 에이전트에게 맡길 업무 2~3개를 적습니다. 처음에는 **조회 업무만** 권합니다.

```yaml
system: myapp
agent:
  name: myapp-agent
  persona: 영업 담당자가 거래처 미수금과 주문 상태를 빨리 확인하도록 돕는 에이전트
use_cases:
  - id: UC-1
    title: 거래처 미수금 조회
    goal: 거래처 코드로 미수금 합계와 연체 건을 확인한다
    steps: [UC-1/미수금조회]        # 시연할 때 입력할 단계 이름
```

## 6. 업무 시연 녹화 (앱을 띄울 수 있을 때)

```powershell
# ① 수집기 (결과 → workspace\myapp\capture\raw\traces.jsonl)
docker run -d --name automcp-collector -p 4318:4318 -v ${PWD}\capture-kit\otel-collector.yaml:/etc/otelcol/collector.yaml:ro -v ${PWD}\workspace\myapp\capture\raw:/capture otel/opentelemetry-collector-contrib:0.160.0 --config=/etc/otelcol/collector.yaml
```

② 내 앱의 WAS에 OTel 에이전트를 붙입니다. JVM 옵션 한 줄과 환경변수만 추가하고 코드는 고치지 않습니다.
WAS별 설정 위치는 [capture-kit/README.md](../capture-kit/README.md) 3절, 수집기 주소는 `http://localhost:4318`, 에이전트는 v2.31.1입니다.

```powershell
# ③ 녹화: 터미널에 단계 이름 입력 → 브라우저에서 업무 수행 → 다음 단계 이름 → … → q
node recorder/record.mjs --base-url http://localhost:8080/myapp --out workspace/myapp/capture/raw

# ④ 정제 + 상관분석
automcp sanitize-har workspace/myapp/capture/raw/demo.raw.har workspace/myapp/capture/demo.har
automcp correlate workspace/myapp/capture/raw/traces.jsonl --source D:\legacy\myapp --out workspace/myapp/capture
```

`workspace\myapp\capture\endpoint-map.md`에 **단계 → URL → 컨트롤러 → SQL** 표가 보이면 성공입니다.
앱을 띄울 수 없다면 이 단계를 건너뜁니다(설계서에 "캡처 근거 없음" 경고가 붙음).

## 7. 설계서(IR) 만들기 — Claude가 작성

플러그인을 넣은 Claude Code에서:

```
/automcp:explain workspace/myapp
```

DB 접속 정보(종류, 호스트, 서비스명)를 알려 주면 Claude가 `workspace\myapp\mcp-spec.yaml`을 쓰고 lint 오류 0까지 고칩니다.
직접 확인: `automcp lint workspace/myapp/mcp-spec.yaml`

## 8. 검토·승인 — 운영자 역할

```powershell
automcp contract workspace/myapp/mcp-spec.yaml --out workspace/myapp/build/contract.html
```

계약서에서 tool별 목적, 접근 테이블, 원본과 다른 점을 확인한 뒤 Claude Code에서 `/automcp:review workspace/myapp`로
승인·반려와 질문 답변을 알려 줍니다. **승인된 tool만 생성됩니다.**

## 9. MCP 서버 생성·실행·검증

```powershell
automcp compile workspace/myapp/mcp-spec.yaml --out workspace/myapp/build
```

DB에 **조회 전용 계정**을 먼저 만드세요(Oracle은 민감 컬럼을 뺀 뷰도, [capture-kit/README.md](../capture-kit/README.md) 7절).
DB가 내 PC에 있으면 IR의 host는 `host.docker.internal`이어야 합니다.

```powershell
docker run -d --name myapp-toolbox -p 5002:5000 -v ${PWD}\workspace\myapp\build:/config:ro -e MCP_DB_USER=<계정> -e MCP_DB_PASSWORD=<비밀번호> us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:1.12.0 --config /config/tools.yaml --address 0.0.0.0 --port 5000
automcp verify workspace/myapp/mcp-spec.yaml --url http://localhost:5002/mcp/<agent.name>
```

전부 PASS면 성공입니다. **golden 실패**는 시연 화면과 결과가 다르다는 뜻이고(SQL·변환 수정),
**guard 실패**는 보안 문제입니다(반드시 수정).

## 10. 에이전트 평가 (선택)

[examples/jpetstore/eval.yaml](../examples/jpetstore/eval.yaml)을 참고해 `workspace\myapp\eval.yaml`에
현업이 실제로 할 질문 3~5개와 정답에 들어갈 값을 적습니다.

```powershell
automcp eval workspace/myapp/eval.yaml --url http://localhost:5002/mcp/<agent.name> --model sonnet
```

질문 하나에 약 $0.07가 듭니다.

## 막힐 때

| 증상 | 확인할 것 |
|---|---|
| `traces.jsonl`이 비어 있음 | WAS 로그에 `opentelemetry-javaagent` 줄이 있는지, 수집기 주소가 맞는지 |
| 엔드포인트 맵에 SQL이 없음 | 캐시 적중일 수 있음. WAS 재시작 직후 다시 시연 |
| "매퍼 미매칭" | 동적 SQL이나 매퍼 밖 JDBC. explain 단계에서 SQL 원문으로 처리 |
| verify 결과 필드가 `None` | Oracle 대문자 별칭 문제. `compile`을 다시 실행(컴파일러가 보정) |
| 응답 한글이 깨짐 | IR의 `system.http.charset`을 `MS949`로 |
| Toolbox가 DB에 못 붙음 | 컨테이너 안의 `localhost`는 자기 자신. `host.docker.internal` 사용 |
