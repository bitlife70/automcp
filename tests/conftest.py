import copy
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "jpetstore"
SOURCE = ROOT / "targets" / "jpetstore-6"

needs_source = pytest.mark.skipif(not SOURCE.exists(), reason="targets/jpetstore-6 소스가 없음 (README 참고해 clone)")


@pytest.fixture
def example_data():
    return yaml.safe_load((EXAMPLE / "mcp-spec.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def write_spec(tmp_path):
    """IR dict를 예제와 같은 상대경로 구조로 임시 폴더에 써서 Spec으로 로드한다."""
    from automcp import ir

    def _write(data, name="mcp-spec.yaml"):
        work = tmp_path / "examples" / "jpetstore"
        (work / "capture").mkdir(parents=True, exist_ok=True)
        for f in ("endpoint-map.json", "demo.har"):
            src = EXAMPLE / "capture" / f
            if src.exists() and not (work / "capture" / f).exists():
                shutil.copy(src, work / "capture" / f)
        data = copy.deepcopy(data)
        data["system"]["source_root"] = str(SOURCE)
        path = work / name
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return ir.load(path)

    return _write


def tool(data, name):
    return next(t for t in data["tools"] if t["name"] == name)
