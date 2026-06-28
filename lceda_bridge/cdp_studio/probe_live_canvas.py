#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话 2i 取证:经 worker 总线读取**活体已建工程**的真实 canvas 记录结构。

证明"融为一体":对刚由 build_blinker 建出的工程,绕过 GUI/EXTAPI,直接经私有
worker 总线 extractCanvas/getCanvas 读到记录级板态(器件/网/线的真实 record schema)。

用法:python probe_live_canvas.py <project_uuid> <sheet_uuid>
不带参则自动取当前活动工程 + 其首个 sheet。
"""
import sys
import json
import time

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d  # noqa: E402
import eda_flow  # noqa: E402
import canvas_lowlevel as C  # noqa: E402


def main():
    f = eda_flow.Flow()
    ws = f.ws

    if len(sys.argv) >= 3:
        proj, sheet = sys.argv[1], sys.argv[2]
    else:
        cur = f.call("dmt_Project.getCurrentProjectInfo", timeout=10)
        proj = cur["uuid"]
        b = f.boards()
        sheet = b["schematic"]["page"][0]["uuid"]
    print("[proj]", proj, "[sheet]", sheet)

    # 确保该工程某文档已开 → worker 总线实例化
    f.open_document(sheet, "sch", tries=6, gap=2)
    time.sleep(2)
    bus = C.worker_bus_expr(ws, proj)
    if not bus:
        print("worker 总线未就绪"); return
    print("[bus]", bus)

    # getCanvas:sheet 元数据
    gc, err = C.get_canvas(ws, bus, sheet)
    print("[getCanvas]", (gc or err)[:300] if gc or err else None)

    # extractCanvas:内联 dataSet(devices/symbols/footprints) + parentIds
    ex, err2 = C.extract_canvas(ws, bus, sheet)
    if err2 and not ex:
        print("[extractCanvas ERR]", err2); 
    full = C.wrpc_full(ws)
    if full:
        try:
            obj = json.loads(full)
        except Exception as e:
            print("[parse ERR]", e); return
        ds = obj.get("dataSet") or {}
        summary = {k: (len(v) if hasattr(v, "__len__") else v) for k, v in ds.items()}
        print("[extractCanvas dataSet sizes]", json.dumps(summary, ensure_ascii=False))
        print("[parentIds keys]", list((obj.get("parentIds") or {}).keys())[:20])
        out = "_cmp/live_blinker_canvas.json"
        import os
        os.makedirs("_cmp", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        print("[dumped]", out, "bytes=", len(full))


if __name__ == "__main__":
    main()
