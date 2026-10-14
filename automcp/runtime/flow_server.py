"""automcp http-flow MCP 서버 (Streamable HTTP).

  python -m automcp.runtime.flow_server --config flows.yaml --port 5100

flows.yaml은 `automcp compile`이 IR의 http-flow tool(승인분)로부터 생성한다.
"""

import argparse
import contextlib
import json
import os

import uvicorn
import yaml
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from .flow import FlowError, FlowRunner, IdempotencyStore

JSON_TYPE = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}


def tool_schema(tool):
    props = {n: {"type": JSON_TYPE[p["type"]], "description": p["description"]} for n, p in tool["input"].items()}
    required = [n for n, p in tool["input"].items() if p.get("required", True)]
    write = tool["side_effect"] != "read"
    return types.Tool(
        name=tool["name"],
        description=tool["description"],
        inputSchema={"type": "object", "properties": props, "required": required, "additionalProperties": False},
        annotations=types.ToolAnnotations(
            readOnlyHint=not write,
            destructiveHint=tool["side_effect"] == "destructive",
            idempotentHint=bool(tool.get("idempotency_key")),
            openWorldHint=False,
        ),
    )


def build_app(config, state_path, allowed_hosts):
    tools = {t["name"]: t for t in config["tools"]}
    runner = FlowRunner(config, store=IdempotencyStore(state_path))
    server = Server(config.get("name", "automcp-flow"))

    @server.list_tools()
    async def list_tools():
        return [tool_schema(t) for t in tools.values()]

    @server.call_tool()
    async def call_tool(name, arguments):
        tool = tools.get(name)
        if tool is None:
            raise ValueError(f"알 수 없는 tool: {name}")
        try:
            result = await runner.run(tool, arguments or {})
        except FlowError as e:
            # 레거시 화면의 실패 사유를 에이전트가 이해할 수 있게 그대로 전달 (isError=True)
            raise RuntimeError(str(e)) from e
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    manager = StreamableHTTPSessionManager(
        app=server, stateless=True, json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts, allowed_origins=[]),
    )

    async def handle(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    return Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5100)
    p.add_argument("--state", default=os.environ.get("AUTOMCP_STATE", "/state/idempotency.db"))
    a = p.parse_args()
    with open(a.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    hosts = os.environ.get("ALLOWED_HOSTS", f"localhost:{a.port},127.0.0.1:{a.port}").split(",")
    uvicorn.run(build_app(config, a.state, hosts), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
