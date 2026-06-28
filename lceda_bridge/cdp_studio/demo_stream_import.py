# -*- coding: utf-8 -*-
"""demo_stream_import — 超大工程(169MB X86 主板)分块流式 import 实战。

突破「单帧透传上限」:把 169MB .epru 分块(base64,每帧 ≤chunk)流入页内
window.__epru,再令 worker import 直接引用该变量 → 单帧不再承载全量,而
parseExport3_0 仍拿到完整无损 dataStr。全程零 GUI。

用法:python demo_stream_import.py [src_epro2_path | oshwhub_uuid]
默认用本地缓存 _x86.epro2(169.6MB epru,1980 子文档)。
"""
import json
import os
import sys
import time

sys.path.insert(0, ".")
import canvas_lowlevel as C
import demo_project_clone as dpc
import eda_flow
import reverse_analyze as ra

X86_EPRO2 = "_x86.epro2"
X86_OSHWHUB = "d8d6e6f0f0a04d7e8c2a3b1c5e6f7a8b"  # 仅占位;默认走本地缓存


def run(src=X86_EPRO2, chunk_mb=4):
    f = eda_flow.Flow()
    ws = f.ws
    out = {"chunk_mb": chunk_mb}

    # 1) 载入超大 .epru -------------------------------------------------------
    if not os.path.exists(src):  # 当作 oshwhub uuid,经社区端点取整包并落盘
        import resource_registry as rr
        epro2 = rr.get_community_epro2(src, ws=ws)
        src = "_x86_fetched.epro2"
        open(src, "wb").write(epro2)
    epru, imgs = ra.load_epru(src)
    out["epru_bytes"] = len(epru)
    out["src_live_docs"] = dpc.doc_counts(epru, live_only=True)
    print("源 .epru: %.1f MB | 活动子文档: %s" % (len(epru) / 1048576, out["src_live_docs"]))

    # 2) 建空工程 + 打开文档使 worker 实例化 ----------------------------------
    clone = f.create_project("DAO_STREAM_%d" % int(time.time()))
    out["clone"] = clone
    b = f.poll_boards()
    try:
        f.open_document(b[0]["schematic"]["page"][0]["uuid"], "sch")
    except Exception as e:
        print("open_document warn:", repr(e)[:120])
    bus = C.worker_bus_expr(ws, clone)
    if not bus:
        raise RuntimeError("worker 总线未实例化")

    # 3) 分块流式灌库 ---------------------------------------------------------
    t0 = time.time()
    tag, err, page_len, nchunks = C.import_project_streamed(
        ws, bus, clone, epru, chunk_bytes=chunk_mb * 1024 * 1024, wait=900)
    out["stream_chunks"] = nchunks
    out["page_assembled_len"] = page_len
    out["page_eq_src"] = (page_len == len(epru))
    out["import_seconds"] = round(time.time() - t0, 1)
    if err:
        out["import_err"] = err
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return out
    result = json.loads(C.wrpc_full(ws))
    m = result.get("result", {}).get("map", {})
    out["import_map"] = {k: len(v) for k, v in m.items() if isinstance(v, dict)}
    print("流式 import OK %ds,%d 块,页内字节=%s(=源:%s)" %
          (out["import_seconds"], nchunks, page_len, out["page_eq_src"]))
    print("import 映射:", out["import_map"])

    # 4) 落库 + 服务器回读验证 -----------------------------------------------
    try:
        f.call("sch_Document.save", timeout=30)
    except Exception as e:
        print("save warn:", repr(e)[:100])
    time.sleep(8)
    try:
        clone_bytes, _ = dpc.download_epro2(ws, clone, timeout=180)
        out["clone_live_docs"] = dpc.doc_counts(dpc.epru_text(clone_bytes), live_only=True)
        print("克隆服务器回读 活动子文档:", out["clone_live_docs"])
    except Exception as e:
        out["readback_warn"] = repr(e)[:160]
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else X86_EPRO2
    cm = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    r = run(src, cm)
    os.makedirs("_cmp", exist_ok=True)
    json.dump(r, open("_cmp/stream_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(r, ensure_ascii=False, indent=2))
