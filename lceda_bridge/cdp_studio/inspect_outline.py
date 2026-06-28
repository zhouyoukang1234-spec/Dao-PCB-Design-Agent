#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect_outline — 枚举密板 layer-11 板框 Polyline 与所有焊盘,定位贴近 J3 的杂散板框几何。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_flow

PROJECT = "cef6a7a6ec96439b94ba49facc0af907"
PCB = "8149127710fe8519"


def main():
    f = eda_flow.Flow()
    f.open_project(PROJECT)
    f.open_document(PCB)
    time.sleep(3)
    poly_ids = f.eda.call("pcb_PrimitivePolyline.getAllPrimitiveId", timeout=15) or []
    print("polyline count:", len(poly_ids))
    polys = []
    for pid in poly_ids:
        g = f.eda.call("pcb_PrimitivePolyline.get", pid, timeout=10)
        polys.append((pid, g))
        print("POLY", pid, "layer=", (g or {}).get("layer"),
              "json=", json.dumps(g, ensure_ascii=False)[:300])
    # 所有焊盘坐标
    pads = f.eda.call("pcb_PrimitivePad.getAllPrimitiveId", timeout=15) or []
    padpos = []
    for p in pads:
        g = f.eda.call("pcb_PrimitivePad.get", p, timeout=8)
        if g and "x" in g:
            padpos.append((p, g.get("x"), g.get("y"), g.get("net"), g.get("hole"), g.get("padHole")))
    print("pad count:", len(padpos))
    # 打印带 hole 的(插孔)焊盘
    for p, x, y, net, hole, ph in padpos:
        if hole or ph:
            print("TH PAD", p, "net=", net, "xy=", (x, y), "hole=", hole, "padHole=", ph)


if __name__ == "__main__":
    main()
