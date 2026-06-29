#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ne555_det — 会话 2j:**确定性放件**版 NE555 非稳态振荡器全链路。

进化(已验证):放件改用 `place_device_det`(逆出的 sch_PrimitiveComponent.create
真实签名),按图纸**数据坐标**精确落件,不靠合成鼠标/视口映射;同器件可重复放置不丢件
—— 放件 4/4 精确,严格优于 build_blinker 的合成放件(本轮活体复跑丢件 3/4)。

诚实局限(留作 2k):NE555 多脚网的引脚常**共 x/y**,简单 connect/lane 走线会令不同网
线段重叠融合,故本脚本只有走廊无重叠的网能干净落到 PCB。**已验证的无串扰确定性全链路
最小闭环见 `build_chain_det.py`(RESULT PASS:PCB 2 网无融合)**;NE555 的整网无串扰
自动布线需小型正交布线器(每网走廊 + 每脚让位通道)或网络标签按名连接,列为 2k。

流程:scaffold → 确定性放件(U1+R1+R2+C1)→ 位号 → 存盘 → 连网 → 存盘
→ Update PCB(Apply)→ 板框 → DRC → 导出。放件全程数据坐标确定,可逐次复现。
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
    h = f.scaffold("Dao_NE555det_" + tag)
    print("[scaffold]", h["project"])
    f.open_document(h["page"], kind="sch")
    time.sleep(2)

    ne = f.search_device("NE555")[0]
    ra = f.search_device("0603 10k")[0]
    rb = f.search_device("0603 47k")[0] or f.search_device("0603 100k")[0]
    cap = f.search_device("100nF 0603")[0]

    # 确定性数据坐标布局(单位=10mil)。坐标全部落在 A4 图纸内(右缘~1170)。
    layout = [("U1", ne, 0, 0), ("R1", ra, 300, -150),
              ("R2", rb, 300, 150), ("C1", cap, 300, 400)]
    ids = {}
    for desig, dev, x, y in layout:
        try:
            pid = f.place_device_det(dev, x, y, designator=desig)
            ids[desig] = pid
            print("[place-det]", desig, dev.get("name"), "->", pid, "@", (x, y))
        except Exception as e:
            print("[place-det ERR]", desig, str(e)[:100])
    print("[save]", f.save_sch())
    f.open_document(h["page"], kind="sch")
    time.sleep(3)
    book = set(f.parts())
    ids = {d: p for d, p in ids.items() if p in book}
    print("[parts in book]", sorted(ids), "/4")

    # 连网(NE555 非稳态经典接法):多脚网按链路两两 connect 串接(正交折线,
    # 端点精确落在引脚数据坐标 → 电气真连)。坐标确定后引脚坐标亦确定,连线可复现。
    net_chains = {
        "VCC": [("U1", 8), ("R1", 1)],
        "RA":  [("U1", 7), ("R1", 2), ("R2", 1)],            # DISCH 节点
        "RB":  [("U1", 6), ("R2", 2), ("C1", 1), ("U1", 2)],  # THRES+TRIG 节点
        "GND": [("U1", 1), ("C1", 2)],
    }
    for net, chain in net_chains.items():
        chain = [(d, p) for d, p in chain if d in ids]
        made = 0
        for (da, pa), (db, pb) in zip(chain, chain[1:]):
            try:
                f.connect(ids[da], pa, ids[db], pb, net); made += 1
            except Exception as e:
                print("[wire ERR]", net, "%s.%s-%s.%s" % (da, pa, db, pb), str(e)[:70])
        print("[net]", net, "段数", made)
    print("[save]", f.save_sch())
    time.sleep(2)

    # 连网后回读引脚网名,确证电气真连(确定性放件 + 连线闭环验证)
    f.open_document(h["page"], kind="sch"); time.sleep(2)
    bound = 0
    for desig, pid in ids.items():
        try:
            for p in f.part_pins(pid):
                if p.get("net"):
                    bound += 1
        except Exception:
            pass
    print("[pin-nets bound]", bound)

    print("[sync]", f.sync_to_pcb(h["pcb"]))
    f.open_document(h["pcb"], kind="pcb")
    time.sleep(2)
    print("[pcb comps]", f.call("pcb_PrimitiveComponent.getAllPrimitiveId", timeout=15))
    print("[pcb nets]", f.pcb_nets())

    print("[outline]", f.board_outline(margin=120))
    print("[save pcb]", f.save_pcb(h["pcb"]))
    time.sleep(1)

    try:
        drc = f.drc()
        print("[drc]", json.dumps(drc, ensure_ascii=False)[:400])
    except Exception as e:
        print("[drc ERR]", str(e)[:120])

    outdir = os.path.abspath(os.path.join("exports", "Dao_NE555det_" + tag))
    for fn, nm in [(f.export_gerber, "Gerber"), (f.export_bom, "BOM"),
                   (f.export_pnp, "PNP"), (f.export_netlist, "Netlist")]:
        try:
            print("[export]", nm, fn(outdir, "Dao_NE555det_" + nm))
        except Exception as e:
            print("[export ERR]", nm, str(e)[:120])
    print("[done] project=%s outdir=%s" % (h["project"], outdir))


if __name__ == "__main__":
    main()
