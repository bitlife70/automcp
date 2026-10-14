"""IR(mcp-spec.yaml) 로드·스키마 검증·경로 해석."""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import jsonschema
import yaml

PARAM_RE = re.compile(r"#\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}")   # sql 바인딩: #{name}
FLOW_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")         # http-flow 바인딩: {name}


@cache
def schema():
    return yaml.safe_load((Path(__file__).parent / "schema" / "ir-v1.schema.yaml").read_text(encoding="utf-8"))


@dataclass
class Spec:
    path: Path
    data: dict

    @property
    def base(self) -> Path:
        return self.path.parent

    def resolve(self, rel):
        return (self.base / rel).resolve() if rel else None

    @property
    def source_root(self):
        return self.resolve(self.data["system"].get("source_root"))

    @property
    def capture_path(self):
        return self.resolve(self.data["system"].get("capture"))

    @property
    def har_path(self):
        return self.resolve(self.data["system"].get("har"))

    @property
    def db_type(self):
        return self.data["system"]["database"]["type"]

    @property
    def tools(self):
        return self.data["tools"]

    @property
    def max_rows(self):
        return self.data.get("defaults", {}).get("max_rows", 50)

    @property
    def excluded_columns(self):
        return [c.lower() for c in self.data.get("policies", {}).get("excluded_columns", [])]


def schema_errors(data):
    validator = jsonschema.Draft202012Validator(schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))]


def load(path) -> Spec:
    path = Path(path).resolve()
    return Spec(path, yaml.safe_load(path.read_text(encoding="utf-8")))


def statement_params(statement):
    """#{name} 파라미터를 등장 순서대로 반환한다(중복 포함)."""
    return PARAM_RE.findall(statement)


def tool_matches(ir_name, server_name):
    """IR tool 이름과 서버 측 이름을 대응시킨다. 게이트웨이는 '<upstream>-<tool-slug>' 형태로 이름을 바꾼다."""
    canon = server_name.split("__")[-1].replace("-", "_")
    return canon == ir_name or canon.endswith("_" + ir_name)
