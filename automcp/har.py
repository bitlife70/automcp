"""HAR 정제: 시연 녹화본에서 자격증명·결제정보·세션을 제거한다.

캡처 원본은 고객 내부망 밖으로 나가면 안 된다. 정제본만 분석·검증에 쓴다.
golden replay에 필요한 응답 본문(화면)은 남기되, 민감 패턴은 가린다.
"""

import json
import re
from pathlib import Path

SENSITIVE_FIELD = re.compile(r"pass(word|wd)?|pwd|card|cvv|cvc|expir|exprdate|ssn|jumin|rrn|secret|token", re.I)
SENSITIVE_HEADER = {"cookie", "set-cookie", "authorization", "proxy-authorization", "x-csrf-token", "x-xsrf-token"}
CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){13,19}\b")
RRN = re.compile(r"\b\d{6}-?[1-4]\d{6}\b")  # 주민등록번호
MASK = "***"


def _mask_text(text):
    text = CARD_NUMBER.sub(lambda m: MASK if sum(c.isdigit() for c in m.group()) >= 13 else m.group(), text)
    return RRN.sub(MASK, text)


def _mask_query(qs):
    return re.sub(r"([^&=]+)=([^&]*)",
                  lambda m: f"{m.group(1)}={MASK}" if SENSITIVE_FIELD.search(m.group(1)) else m.group(0), qs)


def sanitize(har):
    stats = {"headers": 0, "params": 0, "bodies": 0}
    for e in har["log"]["entries"]:
        for part in (e["request"], e["response"]):
            for h in part.get("headers", []):
                if h["name"].lower() in SENSITIVE_HEADER:
                    h["value"] = MASK
                    stats["headers"] += 1
            part["cookies"] = []
        req = e["request"]
        for p in req.get("queryString", []):
            if SENSITIVE_FIELD.search(p["name"]):
                p["value"] = MASK
                stats["params"] += 1
        req["url"] = re.sub(r"\?(.*)$", lambda m: "?" + _mask_query(m.group(1)), req["url"])
        post = req.get("postData")
        if post:
            for p in post.get("params", []):
                if SENSITIVE_FIELD.search(p["name"]):
                    p["value"] = MASK
                    stats["params"] += 1
            if "text" in post:
                masked = _mask_query(post["text"]) if "urlencoded" in post.get("mimeType", "") else post["text"]
                post["text"] = _mask_text(masked)
        content = e["response"].get("content", {})
        if content.get("text") and content.get("encoding") != "base64":
            masked = _mask_text(content["text"])
            if masked != content["text"]:
                stats["bodies"] += 1
                content["text"] = masked
    return har, stats


def sanitize_file(src, dst):
    har = json.loads(Path(src).read_text(encoding="utf-8"))
    har, stats = sanitize(har)
    Path(dst).write_text(json.dumps(har, ensure_ascii=False), encoding="utf-8")
    return stats
