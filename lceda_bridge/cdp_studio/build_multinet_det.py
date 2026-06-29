# -*- coding: utf-8 -*-
"""会话 2k —— 多网/多脚 确定性建板 + 无串扰自动布线 端到端实证。

链路:scaffold(或复用已开 board)→ 确定性放件(place_device_det)→
  auto_route 多网汇接(NET_A 三脚 / NET_B 两脚,各走专属 lane,左右分流免相交)→
  importChanges/Apply 同步 PCB → 断言 **PCB 网表 NET_A=3 pad / NET_B=2 pad**(多脚网真连)。

用法:
  python build_multinet_det.py            # 全新 scaffold(新会话冷启动后可用)
  REUSE=1 python build_multinet_det.py    # 复用编辑器当前已打开的 board(本会话实证用)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_flow  # noqa: E402


def main():
    f = eda_flow.Flow()
    tag = time.strftime("%H%M%S")
    if os.environ.get("REUSE") == "1":
        b = f.poll_boards()
        if not b:
            print("[REUSE] 无已打开 board"); return 2
        f.board = b[0]
        h = {"page": f.board["schematic"]["page"][0]["uuid"],
             "pcb": f.board["pcb"]["uuid"]}
        print("[reuse board]", f.board["uuid"][:12])
    else:
        h = f.scaffold("Dao_MultiNet_" + tag)
        print("[scaffold]", h["project"])

    f.open_document(h["page"], kind="sch"); time.sleep(2)
    print("[clear sch]", f.clear_sch_parts()); f.save_sch(); time.sleep(2)

    dev = f.search_device("0603 10k")[0]
    device = {"uuid": dev["uuid"], "libraryUuid": dev["libraryUuid"], "name": dev.get("name")}
    R = [f.place_device_det(device, 0, y, designator="R%d" % (i + 1))
         for i, y in enumerate((0, 300, 600))]
    print("[placed]", len(R)); f.save_sch(); time.sleep(2)

    # pin "2" = 左脚(x=-20), pin "1" = 右脚(x=+20)
    net_map = {
        "NET_A": [(R[0], "2"), (R[1], "2"), (R[2], "2")],   # 三脚网
        "NET_B": [(R[0], "1"), (R[1], "1")],                 # 两脚网
    }
    print("[auto_route lanes]", f.auto_route(net_map))
    f.save_sch(); time.sleep(2)

    print("[sync]", f.sync_to_pcb(h["pcb"]))
    f.open_document(h["pcb"], kind="pcb"); time.sleep(3)
    nets = f.pcb_nets() or []
    comps = f.call("pcb_PrimitiveComponent.getAllPrimitiveId", timeout=15) or []
    print("[pcb comps]", len(comps), "[pcb nets]", nets)

    counts = {}
    for net in ("NET_A", "NET_B"):
        prims = f.call("pcb_Net.getAllPrimitivesByNet", net, timeout=12)
        counts[net] = len(prims) if isinstance(prims, list) else -1
    print("[pad counts]", counts)

    ok = (len(comps) == 3 and counts.get("NET_A") == 3 and counts.get("NET_B") == 2)
    print("[ASSERT] comps=3 | NET_A pad=3 (多脚网) | NET_B pad=2")
    print("[RESULT]", "PASS" if ok else "PARTIAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
