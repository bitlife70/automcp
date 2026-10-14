"""유지보수: 레거시 소스가 바뀌었을 때 영향받는 tool을 찾는다.

컴파일 시 기록한 지문(automcp.lock.json)과 현재 소스를 비교한다.
- 재사용 매퍼 SQL이 바뀜      → 바인딩 SQL 재검토 필요 (BREAKING 가능)
- 근거 소스 줄이 바뀜/사라짐   → 근거 위치 갱신 필요 (줄 이동일 수 있음)
"""

import hashlib
import json
from pathlib import Path

from . import correlate


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def detect(lock_path, source_root):
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    source_root = Path(source_root)
    mappers = {}
    for m in correlate.index_mappers(source_root):
        mappers[m["id"]] = m
        mappers[m["id"].rsplit(".", 2)[-2] + "." + m["id"].rsplit(".", 1)[-1]] = m

    report = {}
    for tool, fp in lock["tools"].items():
        issues = []
        for ref, old in fp.get("mappers", {}).items():
            m = mappers.get(ref)
            if m is None:
                issues.append(("BREAKING", f"매퍼 statement 삭제됨: {ref}"))
            elif _sha(m["sql"]) != old:
                issues.append(("BREAKING", f"매퍼 SQL 변경됨: {ref} ({m['file']}:{m['line']})"))
        for ref, old in fp.get("source", {}).items():
            file, line = ref.rsplit(":", 1)
            path = source_root / file
            if not path.is_file():
                issues.append(("BREAKING", f"근거 파일 삭제됨: {file}"))
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if int(line) <= len(lines) and _sha(lines[int(line) - 1].strip()) == old:
                continue
            moved = [i + 1 for i, l in enumerate(lines) if _sha(l.strip()) == old]
            issues.append(("MOVED", f"근거 줄 이동: {ref} → {file}:{moved[0]}") if moved
                          else ("CHANGED", f"근거 줄 변경됨: {ref}"))
        report[tool] = issues
    return report
