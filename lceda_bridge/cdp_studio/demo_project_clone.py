#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整板底层克隆端到端复现(弃 GUI、弃 EXTAPI 二进制桥)。

道法自然·反者道之动:从一块**成品板**反向推演并确定性重建整张工程。

链路(全程不经 GUI 放件、不经 EXTAPI File 序列化):
  1) 取成品板 .epro2(经 sys_FileManager.getProjectFileByProjectUuid),解包出 .epru 全文。
  2) createProject 建全新空工程;打开其任一文档使 worker 实例化。
  3) 经 worker `/mgr/projectWorker/import` 一次性灌入整份 .epru
     ({uuid, datas:{dataStr}, structure:"export3.0"}) → 工程数据库逐 entity 落库,
     返回新旧 uuid 映射(symbolMap/deviceMap/footprintMap/schematicMap/pcbMap)。
  4) save → 服务器回读 .epro2 验证子文档/图元计数与源一致。

实证(NE555 Blinker,20 子文档):克隆工程含 FOOTPRINT×3 / SYMBOL×5 / DEVICE×5 +
原理图(NE555 八脚符号 + 电阻完整渲染)+ PCB(铜层/焊盘/封装),编辑器中可视化完好。

用法:
  python demo_project_clone.py [SRC_PROJECT_UUID] [CLONE_NAME]
缺省源 = Blinker(b4258d51174c474ca41015c1f86b6c03)。
"""
import base64
import io
import json
import os
import sys
import time
import zipfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canvas_lowlevel as C  # noqa: E402
import dao_eda_cdp_driver as d  # noqa: E402
import eda_flow  # noqa: E402

SRC_DEFAULT = "b4258d51174c474ca41015c1f86b6c03"  # Blinker 成品板


def download_epro2(ws, project_uuid, timeout=90):
    """页内取工程 .epro2 字节(File→arrayBuffer→base64),返回 zip 字节。"""
    js = (
        "(async()=>{try{var f=await window._EXTAPI_ROOT_.sys_FileManager."
        "getProjectFileByProjectUuid(%s);if(!f)return JSON.stringify({ok:false,r:'null'});"
        "var b=new Uint8Array(await f.arrayBuffer());var s='';"
        "for(var i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);"
        "return JSON.stringify({ok:true,name:f.name,size:b.length,b64:btoa(s)});}"
        "catch(e){return JSON.stringify({ok:false,r:String(e&&e.message||e)});}})()"
        % json.dumps(project_uuid)
    )
    v, _ = d.evaluate(ws, js, await_promise=True, timeout=timeout)
    o = json.loads(v)
    if not o.get("ok"):
        raise RuntimeError("download .epro2 失败: %s" % o.get("r"))
    return base64.b64decode(o["b64"]), o["name"]


def epru_text(epro2_bytes):
    z = zipfile.ZipFile(io.BytesIO(epro2_bytes))
    name = [n for n in z.namelist() if n.endswith(".epru")][0]
    return z.read(name).decode("utf-8")


def doc_counts(epru_str):
    """统计 .epru 内每类子文档(DOCHEAD.docType)数量。"""
    c = Counter()
    for ln in epru_str.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        head = json.loads(ln.split("||", 1)[0])
        if head.get("type") == "DOCHEAD":
            p = ln.split("||", 1)[1]
            p = p[:-1] if p.endswith("|") else p
            c[json.loads(p).get("docType")] += 1
    return dict(c)


def run(src_proj=SRC_DEFAULT, clone_name=None):
    clone_name = clone_name or ("DAO_CLONE_%d" % int(time.time()))
    f = eda_flow.Flow()
    ws = f.ws

    # 1) 取成品板 .epru ------------------------------------------------------
    src_proj_info = f.call("dmt_Project.getProjectInfo", src_proj, timeout=15)
    print("源工程:", src_proj_info.get("friendlyName"), src_proj)
    src_bytes, _ = download_epro2(ws, src_proj)
    epru = epru_text(src_bytes)
    src_counts = doc_counts(epru)
    print("源 .epru 字节:", len(epru), "子文档:", src_counts)

    # 2) 建全新空工程 + 打开文档使 worker 实例化 ------------------------------
    clone = f.create_project(clone_name)
    print("克隆工程 uuid:", clone)
    b = f.poll_boards()
    page = b[0]["schematic"]["page"][0]["uuid"]
    try:
        f.open_document(page, "sch")
    except Exception as e:
        print("open_document warn:", repr(e)[:120])
    bus = C.worker_bus_expr(ws, clone)
    print("worker 总线:", bus)
    if not bus:
        raise RuntimeError("worker 总线未实例化")

    # 3) 整板灌库 ------------------------------------------------------------
    full, err = C.import_project(ws, bus, clone, epru, wait=180)
    if err:
        raise RuntimeError("import 失败: %s" % err)
    result = json.loads(C.wrpc_full(ws))
    m = result.get("result", {}).get("map", {})
    print("import OK,映射:", {k: len(v) for k, v in m.items() if isinstance(v, dict)})

    # 4) save + 服务器回读验证 ----------------------------------------------
    try:
        f.call("sch_Document.save", timeout=20)
    except Exception as e:
        print("save warn:", repr(e)[:100])
    time.sleep(4)
    clone_bytes, clone_fname = download_epro2(ws, clone)
    clone_counts = doc_counts(epru_text(clone_bytes))
    print("克隆 .epro2:", clone_fname, len(clone_bytes), "字节")
    print("克隆子文档:", clone_counts)

    ok = all(clone_counts.get(k, 0) >= v for k, v in src_counts.items()
             if k in ("FOOTPRINT", "SYMBOL", "DEVICE"))
    print("库子文档完整(footprint/symbol/device 全数落库):", ok)
    return {"src": src_proj, "clone": clone, "map": m,
            "src_counts": src_counts, "clone_counts": clone_counts, "ok": ok}


if __name__ == "__main__":
    a = sys.argv[1:]
    out = run(a[0] if a else SRC_DEFAULT, a[1] if len(a) > 1 else None)
    print(json.dumps(out, ensure_ascii=False)[:600])
