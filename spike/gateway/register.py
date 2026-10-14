"""MCP 게이트웨이(ContextForge)에 automcp 런타임을 등록하고 에이전트용 가상 서버를 만든다.

  python register.py            # spike/ 에서 docker compose가 떠 있는 상태로 실행

- 읽기 런타임(Toolbox)과 쓰기 런타임(flow-runtime)을 각각 upstream gateway로 등록
- 두 런타임의 tool을 묶은 가상 서버(cs-agent) 생성 → 에이전트는 엔드포인트 하나 + Bearer 토큰으로 접속
- 토큰은 spike/gateway/.token 에만 저장(git 제외)
"""

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
GW = "http://localhost:4444"
UPSTREAMS = [
    {"name": "jpetstore-read", "url": "http://toolbox:5000/mcp/cs-agent", "description": "automcp Toolbox 런타임(조회)"},
    {"name": "jpetstore-write", "url": "http://flow-runtime:5100/mcp/", "description": "automcp flow 런타임(쓰기)"},
]
VIRTUAL_SERVER = {"name": "cs-agent", "description": "jpetstore 고객상담 에이전트 (automcp 생성)"}


def env_value(key):
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    raise KeyError(key)


def make_token():
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "gateway", "python3", "-m", "mcpgateway.utils.create_jwt_token",
         "--username", env_value("PLATFORM_ADMIN_EMAIL"), "--exp", "10080", "--secret", env_value("JWT_SECRET_KEY")],
        cwd=HERE.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return out.stdout.strip().splitlines()[-1]


def api(method, path, token, body=None):
    req = urllib.request.Request(GW + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → {e.code}: {e.read().decode()[:300]}") from e


def items(resp):
    return resp if isinstance(resp, list) else resp.get("items") or resp.get("data") or []


def main():
    token = make_token()
    (HERE / ".token").write_text(token, encoding="utf-8")

    existing = {g["name"]: g for g in items(api("GET", "/gateways", token))}
    gw_ids = []
    for up in UPSTREAMS:
        if up["name"] in existing:
            gw = existing[up["name"]]
            print(f"  = upstream {up['name']} (이미 등록)")
        else:
            gw = api("POST", "/gateways", token, {**up, "transport": "STREAMABLEHTTP"})
            print(f"  + upstream {up['name']} → {up['url']}")
        gw_ids.append(gw["id"])

    time.sleep(2)
    tools = [t for t in items(api("GET", "/tools?limit=0", token)) if t.get("gatewayId") in gw_ids]
    print(f"  tool {len(tools)}개 발견: {sorted(t['name'] for t in tools)}")

    servers = {s["name"]: s for s in items(api("GET", "/servers", token))}
    if VIRTUAL_SERVER["name"] in servers:
        srv = api("PUT", f"/servers/{servers[VIRTUAL_SERVER['name']]['id']}", token,
                  {"server": {**VIRTUAL_SERVER, "associated_tools": [t["id"] for t in tools]}}) or servers[VIRTUAL_SERVER["name"]]
    else:
        srv = api("POST", "/servers", token, {"server": {**VIRTUAL_SERVER, "associated_tools": [t["id"] for t in tools]}})
    url = f"{GW}/servers/{srv['id']}/mcp"
    (HERE / ".server-url").write_text(url, encoding="utf-8")
    print(f"\n가상 서버 {VIRTUAL_SERVER['name']}: {url}\n토큰: spike/gateway/.token (Authorization: Bearer ...)")


if __name__ == "__main__":
    main()
