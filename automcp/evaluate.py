"""L3 에이전트 평가: 실제 Claude 에이전트가 생성된 MCP tool만으로 업무 질문을 해결하는지 확인한다.

Claude Code 헤드리스 모드(`claude -p`)로 시나리오마다 에이전트를 실행하고 다음을 검사한다.
- tools_used      : 반드시 호출해야 하는 tool
- tools_forbidden : 호출하면 안 되는 tool (예: 조회 질문에서 주문 tool)
- answer_matches  : 답변에 있어야 하는 내용(정규식)
- answer_excludes : 답변에 있으면 안 되는 내용(정규식, 예: 카드번호)
"""

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .ir import tool_matches


@dataclass
class Outcome:
    id: str
    ok: bool
    problems: list
    tools: list
    answer: str
    seconds: float
    cost_usd: float = 0.0
    turns: int = 0
    extra: dict = field(default_factory=dict)


def _run_claude(prompt, system, mcp_config, max_turns, model, timeout):
    cmd = [shutil.which("claude") or "claude", "-p", prompt,
           "--output-format", "stream-json", "--verbose",
           "--mcp-config", mcp_config, "--strict-mcp-config",
           "--allowedTools", "mcp__*",
           "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,Agent,NotebookEdit",
           "--append-system-prompt", system,
           "--max-turns", str(max_turns)]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return proc.returncode, events, proc.stderr


def _parse(events):
    tools, answer, cost, turns = [], "", 0.0, 0
    for ev in events:
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools.append(block["name"].split("__")[-1])
        elif ev.get("type") == "result":
            answer = ev.get("result", "") or ""
            cost = ev.get("total_cost_usd", 0.0) or 0.0
            turns = ev.get("num_turns", 0) or 0
    return tools, answer, cost, turns


def run(eval_path, mcp_urls, only=None, model=None, timeout=300, headers=None):
    cfg = yaml.safe_load(Path(eval_path).read_text(encoding="utf-8"))
    servers = {f"s{i}": {"type": "http", "url": u, **({"headers": headers} if headers else {})}
               for i, u in enumerate(mcp_urls)}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"mcpServers": servers}, f)
        mcp_config = f.name
    system = cfg.get("system_prompt", "")
    outcomes = []
    for sc in cfg["scenarios"]:
        if only and sc["id"] not in only:
            continue
        t0 = time.time()
        code, events, stderr = _run_claude(sc["prompt"], system, mcp_config, sc.get("max_turns", 8), model, timeout)
        tools, answer, cost, turns = _parse(events)
        exp, problems = sc["expect"], []
        if code != 0 and not answer:
            problems.append(f"claude 실행 실패(code {code}): {stderr.strip()[:200]}")
        for t in exp.get("tools_used", []):
            if not any(tool_matches(t, u) for u in tools):
                problems.append(f"tool 미사용: {t}")
        for t in exp.get("tools_forbidden", []):
            if any(tool_matches(t, u) for u in tools):
                problems.append(f"금지 tool 사용: {t}")
        for pat in exp.get("answer_matches", []):
            if not re.search(pat, answer, re.I | re.S):
                problems.append(f"답변에 없음: /{pat}/")
        for pat in exp.get("answer_excludes", []):
            if re.search(pat, answer, re.I | re.S):
                problems.append(f"답변에 노출: /{pat}/")
        outcomes.append(Outcome(sc["id"], not problems, problems, tools, answer, time.time() - t0, cost, turns))
    Path(mcp_config).unlink(missing_ok=True)
    return outcomes
