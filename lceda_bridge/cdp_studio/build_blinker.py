#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_blinker — 一键全程序化全链路:NE555 非稳态多谐振荡器(LED 闪烁)。

scaffold → 放件(NE555+R1+R2+C1)→ 位号 → 存盘 → 连线成网 → Update PCB(Apply)
→ 板框 → 存盘 → DRC → 导出 Gerber/BOM/PNP/Netlist。

本脚本是本会话"道法自然·实践得真知"确立的全链路的可复现固化件。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_flow


def main():
    f = eda_flow.Flow()
    tag = time.strftime("%H%M%S")
    h = f.scaffold("Dao_Blinker_" + tag)
    print("[scaffold]", h["project"])
    assert f.call("dmt_Project.getCurrentProjectInfo")["uuid"] == h["project"], "活动工程未切换"
    f.open_document(h["page"], kind="sch")

    ne = f.search_device("NE555")[0]
    res = f.search_device("0603 10k")[0]
    cap = f.search_device("100nF 0603")[0]

    # 放件(画布像素,留足间距)
    layout = [("U1", ne, 470, 250), ("R1", res, 730, 180),
              ("R2", res, 730, 330), ("C1", cap, 470, 460)]
    ids = {}
    for desig, dev, px, py in layout:
        pid = f.place_device(dev, px, py)
        if not pid:
            raise SystemExit("放件失败: " + desig)
        f.set_part(pid, designator=desig)
        ids[desig] = pid
        print("[place]", desig, dev.get("name"), "->", pid)
    print("[save]", f.save_sch())
    time.sleep(2)

    # 连线成网(NE555 非稳态经典接法)
    nets = [
        ("U1", 8, "R1", 1, "VCC"),    # VCC -> R1
        ("U1", 7, "R1", 2, "RA"),     # DISCH -> R1/R2 节点
        ("U1", 7, "R2", 1, "RA"),
        ("U1", 6, "R2", 2, "RB"),     # THRES -> R2 -> C1
        ("U1", 2, "R2", 2, "RB"),     # TRIG 与 THRES 同节点
        ("U1", 6, "C1", 1, "RB"),
        ("U1", 1, "C1", 2, "GND"),    # GND
    ]
    for da, pa, db, pb, net in nets:
        try:
            f.connect(ids[da], pa, ids[db], pb, net)
            print("[wire]", "%s.%d-%s.%d" % (da, pa, db, pb), net)
        except Exception as e:
            print("[wire ERR]", da, pa, db, pb, str(e)[:80])
    print("[save]", f.save_sch())
    time.sleep(2)

    # 同步进 PCB
    print("[sync]", f.sync_to_pcb(h["pcb"]))
    f.open_document(h["pcb"], kind="pcb")
    time.sleep(2)
    print("[pcb comps]", f.call("pcb_PrimitiveComponent.getAllPrimitiveId", timeout=15))
    print("[pcb nets]", f.pcb_nets())

    # 板框 + 存盘
    print("[outline]", f.board_outline(margin=120))
    print("[save pcb]", f.save_pcb(h["pcb"]))
    time.sleep(1)

    # DRC
    try:
        print("[drc]", f.drc())
    except Exception as e:
        print("[drc ERR]", str(e)[:120])

    # 导出
    outdir = os.path.abspath(os.path.join("exports", "Dao_Blinker_" + tag))
    for fn, nm in [(f.export_gerber, "Gerber"), (f.export_bom, "BOM"),
                   (f.export_pnp, "PNP"), (f.export_netlist, "Netlist")]:
        try:
            print("[export]", nm, fn(outdir, "Dao_Blinker_" + nm))
        except Exception as e:
            print("[export ERR]", nm, str(e)[:120])
    print("[done] project=%s outdir=%s" % (h["project"], outdir))


if __name__ == "__main__":
    main()
