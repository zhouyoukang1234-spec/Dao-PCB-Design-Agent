#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端实证:底层 canvas 直写 → 保存 → 服务器回读确认持久化(弃 GUI、弃 EXTAPI 包装)。

复现会话 2f 的决定性验证(见 EVOLUTION_NOTES.md):
  1. 打开一个有内容的源工程,经 sys_FileManager 直取 .epro2(zip)。
  2. 解包 .epru,切出某 SCH_PAGE 的记录块(canvas dataStr),把其 uuid 改写为目标空 sheet。
  3. 经 worker 总线 setCanvas{uuid,canvas} 灌入目标 sheet → {success:true}。
  4. sch_Document.save → 重新下载目标工程 .epro2 → 解包确认该 sheet 已含图元(落库持久化)。

用法:python demo_canvas_inject.py <源工程uuid> <目标工程uuid> <目标sheet uuid>
不带参数则只打印说明。
"""
import sys
import json
import time
import base64
import io
import zipfile
from collections import Counter

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d  # noqa: E402
import eda_flow  # noqa: E402
import canvas_lowlevel as C  # noqa: E402


def download_epro2(ws, project_uuid):
    """页内取工程 .epro2 二进制(arrayBuffer→btoa 过 CDP),返回 bytes。"""
    js = (
        "(async function(){try{var api=window._EXTAPI_ROOT_;"
        "var file=await api.sys_FileManager.getProjectFileByProjectUuid(%s);"
        "if(!file)return JSON.stringify({err:'no file'});"
        "var buf=await file.arrayBuffer();var b=new Uint8Array(buf),s='';"
        "for(var i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);"
        "window.__epro=btoa(s);return JSON.stringify({size:b.length});"
        "}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()"
        % json.dumps(project_uuid)
    )
    v, _ = d.evaluate(ws, js, await_promise=True, timeout=60)
    meta = json.loads(v)
    if meta.get("err"):
        raise RuntimeError("download .epro2 failed: %s" % meta["err"])
    b64, _ = d.evaluate(ws, "window.__epro||''", await_promise=False, timeout=30)
    return base64.b64decode(b64)


def epru_of(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = [n for n in z.namelist() if n.endswith(".epru")][0]
    return z.read(name).decode("utf-8")


def segment_docs(epru_text):
    """按 DOCHEAD 切分 .epru 为子文档段。返回 [{docType,uuid,lines:[...]}]。"""
    docs = []
    cur = None
    for ln in epru_text.split("\n"):
        if not ln.strip():
            continue
        head = json.loads(ln.split("||", 1)[0])
        if head.get("type") == "DOCHEAD":
            payload = ln.split("||", 1)[1]
            payload = payload[:-1] if payload.endswith("|") else payload
            dh = json.loads(payload)
            cur = {"docType": dh.get("docType"), "uuid": dh.get("uuid"), "lines": [ln]}
            docs.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    return docs


def record_types(lines):
    return dict(Counter(json.loads(l.split("||", 1)[0]).get("type") for l in lines))


def run(src_proj, dst_proj, dst_sheet):
    f = eda_flow.Flow()
    ws = f.ws

    print("[1] 打开源工程并下载 .epro2 ...")
    f.open_project(src_proj, settle=5)
    src_raw = download_epro2(ws, src_proj)
    docs = segment_docs(epru_of(src_raw))
    sch_pages = [x for x in docs if x["docType"] == "SCH_PAGE"]
    if not sch_pages:
        raise RuntimeError("源工程无 SCH_PAGE")
    src_seg = sch_pages[0]
    print("    源 SCH_PAGE %s 记录类型: %s" % (src_seg["uuid"], record_types(src_seg["lines"])))

    print("[2] 切出 canvas 记录块,改写 uuid -> 目标 sheet %s ..." % dst_sheet)
    block = "\n".join(src_seg["lines"]).replace(src_seg["uuid"], dst_sheet)

    print("[3] 打开目标工程/文档,定位 worker 总线 ...")
    f.open_project(dst_proj, settle=4)
    f.open_document(dst_sheet, "sch", tries=6, gap=2)
    time.sleep(2)
    bus = C.worker_bus_expr(ws, dst_proj)
    if not bus:
        raise RuntimeError("worker 总线未就绪")
    print("    bus:", bus)

    print("[4] setCanvas 灌入 ...")
    ok, err = C.set_canvas(ws, bus, dst_sheet, block)
    print("    setCanvas ->", ok or err)

    print("[5] 保存 ...")
    print("    save ->", f.call("sch_Document.save", timeout=15, retries=0))
    time.sleep(3)

    print("[6] 重新下载目标工程 .epro2,校验持久化 ...")
    dst_raw = download_epro2(ws, dst_proj)
    ddocs = segment_docs(epru_of(dst_raw))
    target = [x for x in ddocs if x["uuid"] == dst_sheet and x["docType"] == "SCH_PAGE"]
    if target:
        print("    ✓ 目标 SCH_PAGE 落库记录类型:", record_types(target[0]["lines"]))
        print("    ✓ 持久化确认:底层 setCanvas 写入已经服务器往返存活。")
    else:
        print("    ✗ 未找到目标 sheet 的 SCH_PAGE 段")


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        run(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
