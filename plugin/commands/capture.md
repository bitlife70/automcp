---
description: 레거시 업무 시연을 녹화하고(HAR + 서버 트레이스) 정제·상관분석까지 수행한다
argument-hint: <workspace 폴더> <레거시 base URL> [시나리오 파일]
---

작업 폴더 `$1`, 대상 URL `$2`, 시나리오 `$3`(선택)로 캡처 파이프라인을 실행한다.

1. 사전 확인: 대상 WAS에 캡처 키트가 붙어 있는지 FDE에게 확인한다
   (`capture-kit/README.md`: JVM 옵션 `-javaagent`, OTel 환경변수, 수집기 출력 → `$1/capture/raw/traces.jsonl`).
2. 녹화: 시나리오가 있으면
   `node recorder/record.mjs --base-url $2 --out $1/capture/raw --scenario $3`,
   없으면 대화형 모드로 실행하라고 FDE에게 명령을 안내한다(운영자가 직접 브라우저 조작, 사람이 실행해야 함).
3. 정제: `automcp sanitize-har $1/capture/raw/demo.raw.har $1/capture/demo.har`
4. 상관분석: `automcp correlate $1/capture/raw/traces.jsonl --source <system.source_root> --out $1/capture`
5. `$1/capture/endpoint-map.md`를 요약해서 보여 준다. 매퍼 미매칭 SQL이 있으면 원인(동적 SQL, 매퍼 외 JDBC)을 짚는다.

원본(`capture/raw/`)은 고객 내부망 밖으로 반출하지 않는다는 점을 함께 알린다.
