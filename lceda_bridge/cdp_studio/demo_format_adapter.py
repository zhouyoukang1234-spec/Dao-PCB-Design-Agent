# -*- coding: utf-8 -*-
"""demo_format_adapter — 跨生态格式适配器实战(外部布线器 → JLC,全程零 GUI)。

道并行而不相悖:既突破 JLC 原生 API(逆出 File 过桥导入端点),又把业界开源成果
(FreeRouting 自动布线器)无缝接入。链路:
  JLC PCB --getDsnFile--> Specctra .dsn --[FreeRouting 批量自动布线]--> .ses
       --importAutoRouteSesFile--> JLC PCB(外部布线结果回灌)

本脚本验证回灌端点 `pcb_Document.importAutoRouteSesFile(File)`:把 FreeRouting
产出的 .ses 在页内重建为 File 对象喂入,确认被接受并应用(再导 DSN 看 wiring 变化)。
"""
import base64
import json
import os
import re
import sys
import time

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d
import eda_flow


def _wiring_bytes(dsn_text):
    i = dsn_text.find("(wiring")
    if i < 0:
        return 0, 0
    depth, j = 0, i
    while j < len(dsn_text):
        if dsn_text[j] == "(":
            depth += 1
        elif dsn_text[j] == ")":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    seg = dsn_text[i:j]
    return len(seg), seg.count("(wire ")


def import_ses(f, ses_path, timeout=120):
    """把 .ses 文件在页内重建为 File 并喂入 importAutoRouteSesFile,返回端点结果。"""
    raw = open(ses_path, "rb").read()
    b64 = base64.b64encode(raw).decode()
    js = (
        "(async()=>{try{"
        "var bin=atob(%s);var a=new Uint8Array(bin.length);"
        "for(var i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);"
        "var file=new File([a],'board.ses',{type:'text/plain'});"
        "var r=await window._EXTAPI_ROOT_.pcb_Document.importAutoRouteSesFile(file);"
        "return JSON.stringify({ok:true,ret:(r===undefined?'undefined':r)});"
        "}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
        % json.dumps(b64)
    )
    v, e = d.evaluate(f.ws, js, await_promise=True, timeout=timeout)
    if e:
        return {"ok": False, "transport_err": e}
    return json.loads(v)


def _first_pcb(f):
    for b in f.poll_boards():
        pcb = b.get("pcb")
        if isinstance(pcb, dict) and pcb.get("uuid"):
            return pcb["uuid"]
        if isinstance(pcb, list) and pcb:
            return pcb[0]["uuid"]
    return None


def run(clone_uuid, ses_path="C:/tools/board.ses"):
    f = eda_flow.Flow()
    f.open_project(clone_uuid)
    pcb = _first_pcb(f)
    f.open_document(pcb, "pcb")
    time.sleep(2)
    out = {"clone": clone_uuid, "ses": ses_path, "ses_bytes": os.path.getsize(ses_path)}

    # before:导出 DSN,记录 wiring 规模
    pre = f.export_dsn("_cmp/adapter", name="pre")
    pre_text = open(pre["path"], encoding="utf-8", errors="ignore").read()
    out["wiring_before"] = _wiring_bytes(pre_text)

    # 回灌 FreeRouting .ses
    out["import_result"] = import_ses(f, ses_path)
    time.sleep(4)
    try:
        f.call("pcb_Document.save", timeout=20)
    except Exception as e:
        out["save_warn"] = repr(e)[:100]
    time.sleep(3)

    # after:再导出 DSN,wiring 应反映被回灌的布线
    post = f.export_dsn("_cmp/adapter", name="post")
    post_text = open(post["path"], encoding="utf-8", errors="ignore").read()
    out["wiring_after"] = _wiring_bytes(post_text)
    out["changed"] = out["wiring_after"] != out["wiring_before"]
    return out


if __name__ == "__main__":
    cu = sys.argv[1] if len(sys.argv) > 1 else "0618a4ebcdbc4fff8515279f8ab923ab"
    sp = sys.argv[2] if len(sys.argv) > 2 else "C:/tools/board.ses"
    r = run(cu, sp)
    print(json.dumps(r, ensure_ascii=False, indent=2))
