#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 文件选择器注入:武装 Page.setInterceptFileChooserDialog,捕获 fileChooserOpened
事件,经 DOM.setFileInputFiles 喂入磁盘文件 —— 用于驱动 LCEDA 的 File→Import 向导
(原生文件对话框无法用鼠标自动化,这是确定性的程序化喂文件法)。

用法:后台先跑 `python cdp_file_chooser.py <abs_file_path>` 武装并监听;
随后用 computer 工具点 File→Import→<格式> 触发文件选择 → 本脚本自动塞文件。
"""
import sys, json, time, socket
sys.path.insert(0, ".")
import dao_eda_cdp_driver as d


def arm_and_inject(path, wait=120):
    s = d._editor_session()
    s.cmd("Page.enable", {}, timeout=10)
    s.cmd("DOM.enable", {}, timeout=10)
    s.cmd("Page.setInterceptFileChooserDialog", {"enabled": True}, timeout=10)
    print("ARMED %s" % path, flush=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            s.ws._sock.settimeout(2)
            raw = s.ws.recv()
        except socket.timeout:
            continue
        except Exception as e:
            print("recv_err %s" % e, flush=True)
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("method") == "Page.fileChooserOpened":
            p = msg.get("params", {})
            bnid = p.get("backendNodeId")
            print("CHOOSER backendNodeId=%s mode=%s" % (bnid, p.get("mode")), flush=True)
            try:
                r = s.cmd("DOM.setFileInputFiles",
                          {"files": [path], "backendNodeId": bnid}, timeout=10)
                print("SETFILES_OK %s" % json.dumps(r.get("result", {})), flush=True)
            except Exception as e:
                print("SETFILES_ERR %s" % e, flush=True)
            # 关闭拦截,后续对话框正常显示供继续操作
            try:
                s.cmd("Page.setInterceptFileChooserDialog", {"enabled": False}, timeout=8)
            except Exception:
                pass
            print("DONE", flush=True)
            return True
    print("TIMEOUT_NO_CHOOSER", flush=True)
    return False


if __name__ == "__main__":
    arm_and_inject(sys.argv[1], wait=int(sys.argv[2]) if len(sys.argv) > 2 else 120)
