#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_outline — 在**正确导航(reload_and_reopen)**后的密板上诊断 layer-11 板框几何。

输出:polyline API 方法集 + 每条 polyline 几何 + 板框矩形边 + 每个 TH 焊盘到各边的最近距离,
据此定位「板框→TH 焊盘 0.9mil」违规对应的具体边/焊盘。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d
import eda_flow

PROJECT = "cef6a7a6ec96439b94ba49facc0af907"
PCB = "8149127710fe8519"


def main():
    f = eda_flow.Flow()
    f.open_project(PROJECT)
    f.open_document(PCB)
    time.sleep(2)
    ok = f.reload_and_reopen(PROJECT, PCB)
    print("reload has_outline:", ok)
    time.sleep(2)

    # 1) 探测 polyline namespace 方法集
    R = "window._EXTAPI_ROOT_"
    js = ("(()=>{try{var o=%s.pcb_PrimitivePolyline;"
          "return JSON.stringify(Object.getOwnPropertyNames(Object.getPrototypeOf(o)).concat(Object.keys(o)));"
          "}catch(e){return 'ERR '+e}})()" % R)
    v, e = d.evaluate(f.ws, js, await_promise=False, timeout=15)
    print("polyline methods:", v)

    # 2) 列出所有 polyline 几何
    pids = f.eda.call("pcb_PrimitivePolyline.getAllPrimitiveId", timeout=15) or []
    print("polyline count:", len(pids))
    for pid in pids:
        g = f.eda.call("pcb_PrimitivePolyline.get", pid, timeout=10)
        print("POLY", pid, "layer=", (g or {}).get("layer"), json.dumps(g, ensure_ascii=False)[:400])

    # 3) TH 焊盘
    pads = f.eda.call("pcb_PrimitivePad.getAllPrimitiveId", timeout=15) or []
    th = []
    for p in pads:
        g = f.eda.call("pcb_PrimitivePad.get", p, timeout=8) or {}
        if g.get("hole") or g.get("padHole") or (g.get("padType") in ("through", "TH")):
            th.append((p, g.get("x"), g.get("y"), g.get("net")))
    print("TH pad count:", len(th))
    for p, x, y, net in th:
        print("TH", p, "net=", net, "xy=", (x, y))


if __name__ == "__main__":
    main()
