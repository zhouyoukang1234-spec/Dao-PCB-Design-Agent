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


def doc_counts(epru_str, live_only=False):
    """统计 .epru 内每类子文档(DOCHEAD.docType)数量。

    .epru 是工程的**完整编辑历史字典**,含历史删除的文档(段内带
    `DELETE_DOC{isDelete:true}` 标记)。`live_only=True` 仅统计活动文档,
    与编辑器中实际可见的工程结构一致(否则会把历史删除板误计为活动板)。
    """
    docs = []  # [docType, deleted]
    cur = None
    for ln in epru_str.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        head = json.loads(ln.split("||", 1)[0])
        htype = head.get("type")
        if htype == "DOCHEAD":
            p = ln.split("||", 1)[1]
            p = p[:-1] if p.endswith("|") else p
            cur = [json.loads(p).get("docType"), False]
            docs.append(cur)
        elif cur is not None and htype == "DELETE_DOC":
            cur[1] = True
    c = Counter()
    for dt, deleted in docs:
        if live_only and deleted:
            continue
        c[dt] += 1
    return dict(c)


def _live_struct_docs(epru_str):
    """从 .epru 解析活动(未删除)的结构文档,带其父级引用。

    返回 {'BOARD':[uuid...], 'SCH':[(uuid,boardUuid)...],
          'PCB':[(uuid,boardUuid)...], 'SCH_PAGE':[(uuid,schUuid)...]}。
    """
    out = {"BOARD": [], "SCH": [], "PCB": [], "SCH_PAGE": []}
    cur = None  # [docType, uuid, deleted, meta]
    for ln in epru_str.split("\n"):
        ln = ln.strip()
        if not ln or "||" not in ln:
            continue
        h, p = ln.split("||", 1)
        if p.endswith("|"):
            p = p[:-1]
        head = json.loads(h)
        ty = head.get("type")
        if ty == "DOCHEAD":
            pj = json.loads(p)
            cur = [pj.get("docType"), pj.get("uuid"), False, None]
        elif cur is not None and ty == "DELETE_DOC":
            cur[2] = True
        elif cur is not None and ty == "META" and cur[3] is None:
            try:
                cur[3] = json.loads(p)
            except Exception:
                cur[3] = {}
            dt, uuid, deleted, meta = cur
            if deleted:
                continue
            meta = meta or {}
            if dt == "BOARD":
                out["BOARD"].append(uuid)
            elif dt == "SCH":
                out["SCH"].append((uuid, meta.get("board")))
            elif dt == "PCB":
                out["PCB"].append((uuid, meta.get("board")))
            elif dt == "SCH_PAGE":
                out["SCH_PAGE"].append((uuid, meta.get("schematic")))
    return out


# 已逆出的 worker 端**持久化**结构删除端点(入参均为裸 uuid 字符串):
#   /mgr/projectWorker/board/delete       删板(不级联子文档)
#   /mgr/projectWorker/schematic/delete   删原理图
#   /mgr/projectWorker/pcb/delete         删 PCB
#   /mgr/projectWorker/sheet/delete       删原理图页
# 注意:EXTAPI dmt_Board.deleteBoard 在 Web 仅改编辑器内存模型、**不持久化到服务端**;
# 工程级结构删除必须走下面的 worker 总线(与 import 同处写工程库),方可落库。
WK_DEL = {
    "BOARD": "/mgr/projectWorker/board/delete",
    "SCH": "/mgr/projectWorker/schematic/delete",
    "PCB": "/mgr/projectWorker/pcb/delete",
    "SCH_PAGE": "/mgr/projectWorker/sheet/delete",
}


def prune_to_imported(ws, bus, epru_str, imported_board_uuids, timeout=20):
    """精确克隆:经 worker 总线删除不属于 import 板(boardMap)的板及其级联子文档。

    createProject 自带 1 块空默认板;import 另建被克隆的板。这里把所有 board 不在
    `imported_board_uuids` 的 BOARD/SCH/PCB/SCH_PAGE 经 worker 持久化删除,得到与源
    活动结构精确对齐的克隆(BOARD/SCH/PCB/SCH_PAGE 数 == 源)。
    """
    s = _live_struct_docs(epru_str)
    spurious_boards = set(b for b in s["BOARD"] if b not in imported_board_uuids)
    spurious_sch = {u for u, b in s["SCH"] if b in spurious_boards}
    spurious_pcb = [u for u, b in s["PCB"] if b in spurious_boards]
    spurious_pages = [u for u, sch in s["SCH_PAGE"] if sch in spurious_sch]
    removed = {"BOARD": [], "SCH": [], "PCB": [], "SCH_PAGE": []}
    plan = [("SCH_PAGE", spurious_pages), ("PCB", spurious_pcb),
            ("SCH", sorted(spurious_sch)), ("BOARD", sorted(spurious_boards))]
    for dt, uuids in plan:
        for u in uuids:
            full, err = C.wrpc(ws, bus, WK_DEL[dt], u, wait=timeout)
            ok = (not err) and full and '"success":true' in full
            if ok:
                removed[dt].append(u)
            else:
                print("worker %s 删除告警 %s:" % (dt, u), err or (full or "")[:80])
    return removed


def run(src_proj=SRC_DEFAULT, clone_name=None):
    clone_name = clone_name or ("DAO_CLONE_%d" % int(time.time()))
    f = eda_flow.Flow()
    ws = f.ws

    # 1) 取成品板 .epru ------------------------------------------------------
    src_proj_info = f.call("dmt_Project.getProjectInfo", src_proj, timeout=15)
    print("源工程:", src_proj_info.get("friendlyName"), src_proj)
    src_bytes, _ = download_epro2(ws, src_proj)
    epru = epru_text(src_bytes)
    src_counts = doc_counts(epru, live_only=True)
    src_all = doc_counts(epru)
    print("源 .epru 字节:", len(epru))
    print("源 活动子文档:", src_counts)
    print("源 全量(含历史删除):", src_all)

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

    # 3.5) 精确克隆:经 worker 总线删除不属于 import 板的空默认板及其级联子文档 ----
    imported_boards = set((m.get("boardMap") or {}).values())
    try:
        f.call("sch_Document.save", timeout=20)
    except Exception as e:
        print("save warn:", repr(e)[:100])
    time.sleep(3)
    if imported_boards:
        pre_bytes, _ = download_epro2(ws, clone)
        removed = prune_to_imported(ws, bus, epru_text(pre_bytes), imported_boards)
        if any(removed.values()):
            print("worker 删除冗余结构:", {k: len(v) for k, v in removed.items() if v})

    # 4) save + 服务器回读验证 ----------------------------------------------
    try:
        f.call("sch_Document.save", timeout=20)
    except Exception as e:
        print("save warn:", repr(e)[:100])
    time.sleep(5)
    clone_bytes, clone_fname = download_epro2(ws, clone)
    clone_counts = doc_counts(epru_text(clone_bytes), live_only=True)
    print("克隆 .epro2:", clone_fname, len(clone_bytes), "字节")
    print("克隆 活动子文档:", clone_counts)

    # 完整性:克隆的活动设计应 ≥ 源活动设计(库 + BOARD/SCH/PCB)。删除空默认板后,
    # BOARD/SCH/PCB 应与源活动数精确相等(exact);未删则比源多 1(createProject 默认板)。
    check = ("FOOTPRINT", "SYMBOL", "DEVICE", "BOARD", "SCH", "PCB")
    ok = all(clone_counts.get(k, 0) >= src_counts.get(k, 0) for k in check)
    exact = all(clone_counts.get(k, 0) == src_counts.get(k, 0)
                for k in ("BOARD", "SCH", "PCB"))
    print("活动设计完整(克隆 ≥ 源,逐类):", ok, "| 精确克隆(BOARD/SCH/PCB 相等):", exact)
    return {"src": src_proj, "clone": clone, "map": m,
            "src_live": src_counts, "src_all": src_all,
            "clone_live": clone_counts, "ok": ok, "exact": exact}


if __name__ == "__main__":
    a = sys.argv[1:]
    out = run(a[0] if a else SRC_DEFAULT, a[1] if len(a) > 1 else None)
    print(json.dumps(out, ensure_ascii=False)[:600])
