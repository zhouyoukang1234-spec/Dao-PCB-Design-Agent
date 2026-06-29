#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_chain_det — 会话 2j:**确定性全链路**最小可验证闭环(collision-free)。

确证三件事在同一条链路上同时成立、且**逐次精确可复现**:
  1. 确定性放件(逆出的 `sch_PrimitiveComponent.create`,按图纸数据坐标精确落件,
     同器件可重复放置不丢件)——见 place_device_det。
  2. 程序化连线 → **引脚电气真连**(经 PCB importChanges 落到 PCB 网络验证,
     非依赖不可靠的 sch_Net 即时查询)。
  3. 多网互不串扰:给每条网一条**独立直线走廊**(不同 x,无重叠段)→ 无"多网名"融合。

电路:R1/R2/R3 竖直对齐;NetA=R1.2-R2.2(x=+20 直线),NetB=R2.1-R3.1(x=-20 直线)。
期望:PCB 出现 **2 条网络**、DRC 无致命错。打印断言结果。
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
    h = f.scaffold("Dao_ChainDet_" + tag)
    print("[scaffold]", h["project"])
    f.open_document(h["page"], kind="sch"); time.sleep(2)
    # 干净起步:删空可能的跨次运行残留(同一编辑器内 board 复用时)
    print("[clear sch]", f.clear_sch_parts())
    f.save_sch(); time.sleep(1)

    dev = f.search_device("0603 10k")[0]
    device = {"uuid": dev["uuid"], "libraryUuid": dev["libraryUuid"], "name": dev.get("name")}

    # 确定性放件:同一器件放 3 个,竖直对齐(数据坐标精确)
    ids = {}
    for desig, y in [("R1", 0), ("R2", 300), ("R3", 600)]:
        ids[desig] = f.place_device_det(device, 0, y, designator=desig)
        print("[place-det]", desig, "@(0,%d) ->" % y, ids[desig])
    f.save_sch(); time.sleep(1)
    f.open_document(h["page"], kind="sch"); time.sleep(2)

    # 读引脚精确坐标
    pins = {desig: {str(p["pinNumber"]): (int(round(p["x"])), int(round(p["y"])))
                    for p in f.part_pins(pid)} for desig, pid in ids.items()}
    print("[pins]", json.dumps(pins, ensure_ascii=False))

    # NetA: R1.2 — R2.2(共 x=+20 直线竖段);NetB: R2.1 — R3.1(共 x=-20 直线竖段)
    a1, a2 = pins["R1"]["2"], pins["R2"]["2"]
    b1, b2 = pins["R2"]["1"], pins["R3"]["1"]
    f.wire([a1[0], a1[1], a2[0], a2[1]], "NETA"); print("[wire] NETA", a1, a2)
    f.wire([b1[0], b1[1], b2[0], b2[1]], "NETB"); print("[wire] NETB", b1, b2)
    f.save_sch(); time.sleep(2)

    print("[sync]", f.sync_to_pcb(h["pcb"]))
    f.open_document(h["pcb"], kind="pcb"); time.sleep(2)
    comps = f.call("pcb_PrimitiveComponent.getAllPrimitiveId", timeout=15)
    nets = f.pcb_nets()
    print("[pcb comps]", comps)
    print("[pcb nets]", nets)

    print("[outline]", f.board_outline(margin=120))
    print("[save pcb]", f.save_pcb(h["pcb"]))
    try:
        print("[drc]", json.dumps(f.drc(), ensure_ascii=False)[:300])
    except Exception as e:
        print("[drc ERR]", str(e)[:120])

    outdir = os.path.abspath(os.path.join("exports", "Dao_ChainDet_" + tag))
    for fn, nm in [(f.export_gerber, "Gerber"), (f.export_bom, "BOM"),
                   (f.export_netlist, "Netlist")]:
        try:
            print("[export]", nm, fn(outdir, "Dao_ChainDet_" + nm))
        except Exception as e:
            print("[export ERR]", nm, str(e)[:120])

    # 断言
    ncomp = len(comps) if isinstance(comps, list) else -1
    nnets = len([n for n in (nets or []) if n in ("NETA", "NETB")]) if isinstance(nets, list) else -1
    print("[ASSERT] parts=3 placed=%d | pcb_comps=%d (want 3) | pcb_nets(NETA,NETB)=%d (want 2)"
          % (len(ids), ncomp, nnets))
    print("[RESULT]", "PASS" if (len(ids) == 3 and ncomp == 3 and nnets == 2) else "PARTIAL")
    print("[done] project=%s" % h["project"])


if __name__ == "__main__":
    main()
