#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dao_eda_cdp_driver — 极简 Chrome DevTools Protocol(CDP)客户端 + 嘉立创EDA
Pro Web `window._EXTAPI_ROOT_` 调用封装(零第三方依赖,道法自然·无为而无不为)。

设计要点:
  * 纯 socket 实现 WebSocket(无需 websocket-client),Devin 托管的 Chrome 调试端口
    默认 :29229,随会话常驻。
  * `CDPSession` 连到某个 page target 的 webSocketDebuggerUrl,`cmd()` 发 JSON-RPC。
  * `evaluate()` 在页面主上下文执行 JS(可 await Promise),返回 (value, error)。
  * `call_eda()` 直调 `_EXTAPI_ROOT_.<命名空间>.<方法>(...)`,自动 JSON 序列化入参、
    await Promise、解析回值/异常。
  * `heal_service_workers()` 注销页面 Service Worker 并整页 reload —— 修复本 VM 上
    SW 拦截 /api/* 导致 GUI "Network Error!" 的坑(见 PHASE4_FINDINGS)。

用法:
  python dao_eda_cdp_driver.py probe        # 打印 _EXTAPI_ROOT_ 是否在位 + href
  python dao_eda_cdp_driver.py heal         # 注销 SW + reload
  python dao_eda_cdp_driver.py shot a.png   # 截图编辑器页
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.request

PORT = int(os.environ.get("DAO_CDP_PORT", "29229"))
HOST = os.environ.get("DAO_CDP_HOST", "127.0.0.1")
EDITOR_HINT = "pro.lceda.cn"


# --------------------------------------------------------------------------- #
# CDP target 发现
# --------------------------------------------------------------------------- #
def list_targets(port=None):
    port = port or PORT
    url = "http://%s:%d/json" % (HOST, port)
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.load(r)


def pages(port=None):
    return [t for t in list_targets(port) if t.get("type") == "page"]


def find_page(url_hint=EDITOR_HINT, port=None):
    for t in pages(port):
        if url_hint in (t.get("url") or ""):
            return t
    return None


# --------------------------------------------------------------------------- #
# 极简 WebSocket（客户端帧需掩码）
# --------------------------------------------------------------------------- #
class _WS:
    def __init__(self, ws_url, timeout=20):
        assert ws_url.startswith("ws://") or ws_url.startswith("wss://")
        secure = ws_url.startswith("wss://")
        rest = ws_url.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        path = "/" + path
        if ":" in hostport:
            host, port = hostport.split(":"); port = int(port)
        else:
            host, port = hostport, (443 if secure else 80)
        self._sock = socket.create_connection((host, port), timeout=timeout)
        if secure:
            ctx = ssl._create_unverified_context()
            self._sock = ctx.wrap_socket(self._sock, server_hostname=host)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key)
        )
        self._sock.sendall(handshake.encode())
        resp = self._read_http_headers()
        if "101" not in resp.split("\r\n", 1)[0]:
            raise RuntimeError("WS handshake failed: %s" % resp[:200])
        self._buf = b""

    def _read_http_headers(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("latin-1")

    def send(self, text):
        payload = text.encode("utf-8")
        header = bytearray()
        header.append(0x81)  # FIN + text
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("WS closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """读一帧(自动拼接分片),返回 text。控制帧自动处理。"""
        chunks = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:   # close
                raise ConnectionError("WS close frame")
            if opcode == 0x9:   # ping -> pong
                self._pong(data)
                continue
            if opcode == 0xA:   # pong
                continue
            chunks.append(data)
            if fin:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    def _pong(self, data):
        header = bytearray([0x8A])
        mask = os.urandom(4)
        header.append(0x80 | len(data))
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self._sock.sendall(bytes(header) + masked)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# CDP 会话
# --------------------------------------------------------------------------- #
class CDPSession:
    def __init__(self, ws_url, timeout=20):
        self.ws = _WS(ws_url, timeout=timeout)
        self._id = 0

    def cmd(self, method, params=None, timeout=20):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws._sock.settimeout(max(0.5, deadline - time.time()))
                raw = self.ws.recv()
            except socket.timeout:
                raise TimeoutError("CDP timeout: %s" % method)
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("CDP error %s: %s" % (method, msg["error"]))
                return msg
            # 否则是事件,忽略,继续读
        raise TimeoutError("CDP no-reply: %s" % method)

    def close(self):
        self.ws.close()


# --------------------------------------------------------------------------- #
# 高层:在页面执行 JS
# --------------------------------------------------------------------------- #
def evaluate(ws, expression, await_promise=False, timeout=30, return_by_value=True):
    """在 page 主上下文执行 JS。返回 (value, error)。
    成功:(value, None);异常:(None, '错误文本')。"""
    try:
        r = ws.cmd("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": bool(await_promise),
            "userGesture": True,
            "allowUnsafeEvalBlockedByCSP": True,
        }, timeout=timeout)
    except Exception as ex:
        return None, "EVAL_TRANSPORT: %s" % ex
    res = r.get("result", {})
    if "exceptionDetails" in res:
        ed = res["exceptionDetails"]
        txt = (ed.get("exception", {}) or {}).get("description") or ed.get("text") or json.dumps(ed)
        return None, str(txt)[:500]
    val = res.get("result", {})
    if "value" in val:
        return val["value"], None
    # 未 returnByValue 或对象:回退到 description
    return val.get("description"), None


def _editor_session(navigate=False, url_hint=EDITOR_HINT, port=None, attempts=6):
    """连接编辑器 target。reload 后 target 可能短暂不可达,重试 Runtime.enable。"""
    last = None
    for _ in range(attempts):
        try:
            t = find_page(url_hint, port)
            if not t:
                last = RuntimeError("NO_EDITOR_PAGE")
                time.sleep(2)
                continue
            s = CDPSession(t["webSocketDebuggerUrl"])
            s.cmd("Runtime.enable", {}, timeout=8)
            return s
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def call_eda(ws, dotted, *args, await_promise=True, timeout=30):
    """直调 _EXTAPI_ROOT_.<ns>.<method>(*args)。返回 Python 值;失败抛 RuntimeError。"""
    arglist = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
    js = (
        "(async()=>{try{var R=window._EXTAPI_ROOT_;"
        "if(!R) return JSON.stringify({__ok:false,__e:'NO_EXTAPI'});"
        "var fn=R.%s; var r= (typeof fn==='function')? await R.%s(%s) : fn;"
        "return JSON.stringify({__ok:true,__v:(r===undefined?null:r)});"
        "}catch(e){return JSON.stringify({__ok:false,__e:String(e&&e.message||e)});}})()"
        % (dotted, dotted, arglist)
    )
    v, e = evaluate(ws, js, await_promise=True, timeout=timeout)
    if e:
        raise RuntimeError("call_eda %s -> %s" % (dotted, e))
    try:
        d = json.loads(v)
    except Exception:
        raise RuntimeError("call_eda %s -> bad json: %r" % (dotted, str(v)[:120]))
    if not d.get("__ok"):
        raise RuntimeError("call_eda %s -> %s" % (dotted, d.get("__e")))
    return d.get("__v")


def probe(ws=None):
    """探测 _EXTAPI_ROOT_ 是否在位 + 命名空间数 + href。"""
    own = False
    if ws is None:
        ws = _editor_session(); own = True
    js = (
        "JSON.stringify((function(){var R=window._EXTAPI_ROOT_;"
        "return {ready:(typeof R!=='undefined'&&!!R),"
        "ns:(R?Object.keys(R).length:0),href:location.href};})())"
    )
    v, e = evaluate(ws, js, timeout=10)
    if own:
        ws.close()
    if e:
        return {"ready": False, "err": e}
    return json.loads(v)


def heal_service_workers(ws):
    """注销页面 Service Worker 并整页 reload(修 SW 拦截 /api/* 的坑)。"""
    js = (
        "(async()=>{try{if(!('serviceWorker' in navigator)) return 0;"
        "var rs=await navigator.serviceWorker.getRegistrations();"
        "await Promise.all(rs.map(function(r){return r.unregister();}));"
        "return rs.length;}catch(e){return -1;}})()"
    )
    n, e = evaluate(ws, js, await_promise=True, timeout=20)
    try:
        ws.cmd("Page.enable", {}, timeout=3)
        ws.cmd("Page.reload", {"ignoreCache": True}, timeout=10)
    except Exception as ex:
        return {"unregistered": n, "reloaded": False, "err": str(ex)}
    return {"unregistered": n, "reloaded": True}


def capture_canvas(ws=None, path=None):
    """截图编辑器页(整页 png)。返回 path 或 base64。"""
    own = False
    if ws is None:
        t = find_page()
        if not t:
            raise RuntimeError("NO_EDITOR_PAGE")
        ws = CDPSession(t["webSocketDebuggerUrl"]); own = True
    ws.cmd("Page.enable", {}, timeout=3)
    r = ws.cmd("Page.captureScreenshot", {"format": "png"}, timeout=20)
    data = (r.get("result") or {}).get("data")
    if own:
        ws.close()
    if path:
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path
    return data


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if a == "probe":
        print(json.dumps(probe(), ensure_ascii=False))
    elif a == "targets":
        print(json.dumps([{"type": t.get("type"), "url": t.get("url")} for t in list_targets()], ensure_ascii=False, indent=2))
    elif a == "heal":
        s = _editor_session()
        print(json.dumps(heal_service_workers(s), ensure_ascii=False))
    elif a == "shot":
        print(capture_canvas(path=sys.argv[2] if len(sys.argv) > 2 else "editor.png"))
    else:
        print("unknown:", a)
