"""http-flow 실행 엔진.

레거시 웹 화면 흐름을 그대로 탄다: 로그인 세션 → 다단계 GET/POST → 결과 화면에서 값 추출.
- 호출마다 새 쿠키 세션(사용자 간 세션 공유 없음)
- "@prefilled": 직전 화면 폼의 기본값을 그대로 제출 (결제정보 등은 에이전트를 거치지 않음)
- 문자셋(EUC-KR/MS949 등) 지정 가능
- request_id 기반 멱등성: 성공 결과를 저장해 두고 재호출 시 재실행하지 않음
"""

import json
import os
import re
import sqlite3
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

import httpx

from ..ir import FLOW_PARAM_RE as PARAM
ENV = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


class FlowError(Exception):
    def __init__(self, step, reason, page_text=""):
        self.step, self.reason, self.page_text = step, reason, page_text
        hint = f" 화면 내용: {page_text[:200]}" if page_text else ""
        super().__init__(f"단계 '{step}' 실패: {reason}.{hint}")


class _FormParser(HTMLParser):
    """페이지의 form들과 각 폼의 기본 입력값을 추출한다."""

    def __init__(self):
        super().__init__()
        self.forms, self._cur, self._select, self._option, self._textarea = [], None, None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"action": a.get("action", ""), "method": a.get("method", "get").upper(), "fields": []}
            self.forms.append(self._cur)
        elif self._cur is None:
            return
        elif tag == "input" and a.get("name"):
            kind = a.get("type", "text").lower()
            if kind in ("checkbox", "radio") and "checked" not in a:
                return
            if kind in ("submit", "button", "image", "reset"):
                return
            self._cur["fields"].append((a["name"], a.get("value", "")))
        elif tag == "select" and a.get("name"):
            self._select = {"name": a["name"], "options": []}
        elif tag == "option" and self._select is not None:
            # value 속성이 없으면 옵션 텍스트가 값이다(HTML 규칙, 레거시 JSP에 흔함)
            self._option = {"value": a.get("value"), "text": "", "selected": "selected" in a}
            self._select["options"].append(self._option)
        elif tag == "textarea" and a.get("name"):
            self._textarea = [a["name"], ""]

    def handle_data(self, data):
        if self._option is not None:
            self._option["text"] += data
        if self._textarea is not None:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self._option = None
        elif tag == "select" and self._select is not None and self._cur is not None:
            opts = self._select["options"]
            chosen = next((o for o in opts if o["selected"]), opts[0] if opts else None)
            value = "" if chosen is None else chosen["value"] if chosen["value"] is not None else chosen["text"].strip()
            self._cur["fields"].append((self._select["name"], value))
            self._select = self._option = None
        elif tag == "textarea" and self._textarea is not None and self._cur is not None:
            self._cur["fields"].append(tuple(self._textarea))
            self._textarea = None
        elif tag == "form":
            self._cur = None


def prefilled_form(html, path):
    """action이 path로 끝나는 폼의 기본값 목록. 없으면 None."""
    p = _FormParser()
    p.feed(html)
    for f in p.forms:
        if urllib.parse.urlsplit(f["action"]).path.rstrip("/").endswith(path.rstrip("/")):
            return f["fields"]
    return None


def page_text(html):
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _subst(template, args, quote=False):
    def param(m):
        v = str(args[m.group(1)])
        return urllib.parse.quote(v, safe="") if quote else v

    def env(m):
        v = os.environ.get(m.group(1))
        if v is None:
            raise FlowError("config", f"환경변수 {m.group(1)} 미설정")
        return v

    return ENV.sub(env, PARAM.sub(param, template))


class IdempotencyStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS results (tool TEXT, key TEXT, result TEXT, PRIMARY KEY (tool, key))")

    def get(self, tool, key):
        row = self.db.execute("SELECT result FROM results WHERE tool=? AND key=?", (tool, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, tool, key, result):
        self.db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?)", (tool, key, json.dumps(result, ensure_ascii=False)))
        self.db.commit()


class FlowRunner:
    def __init__(self, config, store=None, transport=None):
        self.base = config["base_url"].rstrip("/")
        self.charset = config.get("charset", "UTF-8")
        self.timeout = config.get("timeout_seconds", 30)
        self.store = store
        self.transport = transport  # 테스트용 httpx MockTransport

    async def _send(self, client, step, args, last_html):
        name = step.get("name", step["path"])
        url = self.base + _subst(step["path"], args, quote=True)
        data = None
        form = step.get("form")
        if form == "@prefilled":
            path = urllib.parse.urlsplit(self.base + step["path"]).path
            fields = prefilled_form(last_html or "", path)
            if fields is None:
                raise FlowError(name, f"직전 화면에 {step['path']}로 제출하는 폼이 없음", page_text(last_html or ""))
            data = fields
        elif isinstance(form, dict):
            data = [(_subst(k, args), _subst(str(v), args)) for k, v in form.items()]
        body = urllib.parse.urlencode(data, encoding=self.charset) if data is not None else None
        headers = {"Content-Type": f"application/x-www-form-urlencoded; charset={self.charset}"} if body else {}
        resp = await client.request(step["method"], url, content=body, headers=headers)
        html = resp.content.decode(self.charset, errors="replace")

        exp = step.get("expect", {})
        if resp.status_code not in exp.get("status", [200]):
            raise FlowError(name, f"HTTP {resp.status_code} (기대 {exp.get('status', [200])})", page_text(html))
        if exp.get("contains") and exp["contains"] not in html:
            raise FlowError(name, f"기대 문구 '{exp['contains']}' 없음", page_text(html))
        extracted = {}
        for field, pattern in exp.get("extract", {}).items():
            m = re.search(pattern, html)
            if not m:
                raise FlowError(name, f"결과 '{field}'를 화면에서 찾지 못함", page_text(html))
            extracted[field] = m.group(1)
        return html, extracted, exp.get("contains")

    async def run(self, tool, args):
        key = args.get(tool.get("idempotency_key", "")) if tool.get("idempotency_key") else None
        if key and self.store:
            prev = self.store.get(tool["name"], key)
            if prev is not None:
                return {**prev, "replayed": True}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, transport=self.transport) as client:
            last_html, result, message = "", {}, None
            login = tool.get("session", {}).get("login")
            if login:
                last_html, _, _ = await self._send(client, {"name": "login", **login}, args, last_html)
            for step in tool["steps"]:
                html, extracted, contains = await self._send(client, step, args, last_html)
                last_html = html or last_html
                result.update(extracted)
                message = contains or message
        result = {**result, "message": message, "replayed": False}
        if key and self.store:
            self.store.put(tool["name"], key, result)
        return result
