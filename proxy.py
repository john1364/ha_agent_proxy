import re
import os, json, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HA = "http://supervisor/core/api"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
AGENT = os.environ.get("AGENT_ID", "conversation.extended_openai_conversation")
PORT = int(os.environ.get("PORT", "8777"))

def ask(text):
    body = json.dumps({"text": text, "agent_id": AGENT, "language": "ru"}).encode()
    req = urllib.request.Request(HA + "/conversation/process", data=body,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    sp = (d.get("response") or {}).get("speech")
    if isinstance(sp, dict):
        sp = (sp.get("plain") or {}).get("speech") or ""
    return sp or ""

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            req = {}
        text = ""
        for m in reversed(req.get("messages") or []):
            if m.get("role") == "user":
                c = m.get("content")
                text = " ".join(x.get("text", "") for x in c) if isinstance(c, list) else str(c or "")
                break
        try:
            ans = ask(text)
            ans = ans.strip()
            if re.fullmatch(r"\(?\s*пуст.*?\)?\s*\.?", ans, flags=re.I) or ans == "":
                ans = "."
        except Exception as e:
            ans = "proxy-error: %s" % e
        model = req.get("model") or "ha-agent"
        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for delta, fin in (({"role": "assistant", "content": ans}, None), ({}, "stop")):
                chunk = {"id": "x", "object": "chat.completion.chunk", "created": 0,
                         "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            resp = {"id": "x", "object": "chat.completion", "created": 0, "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": ans},
                                 "finish_reason": "stop"}]}
            b = json.dumps(resp, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    def do_GET(self):
        body = json.dumps({"ok": True, "token_len": len(TOKEN)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()