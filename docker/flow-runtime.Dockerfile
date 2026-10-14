# automcp http-flow 런타임: 컴파일된 flows.yaml을 읽어 레거시 화면 흐름을 MCP tool로 제공한다.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY automcp ./automcp
RUN pip install --no-cache-dir ".[runtime]"
EXPOSE 5100
CMD ["python", "-m", "automcp.runtime.flow_server", "--config", "/config/flows.yaml", "--port", "5100"]
