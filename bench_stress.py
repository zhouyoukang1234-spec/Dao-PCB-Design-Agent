"""Large complex stress board: multiple ICs wired with real inter-IC signal
buses (not floating nets), decaps per IC, two connectors, multi-rail power,
6 layers. Exercises placement + routing + multi-plane delivery at scale and
surfaces the next bottleneck on a realistic complex topology.
"""
import sys
from collections import Counter

sys.path.insert(0, "/home/ubuntu/Dao-PCB-Design-Agent")
sys.path.insert(0, "/home/ubuntu/Dao-PCB-Design-Agent/dao_kicad")

from dao_kicad.core.auto_designer import (
    auto_design, DesignSpec, ComponentSpec, NetAssignment)
from dao_kicad.core.netclass import BoardCategory
from dao_kicad.core.drc import DrcEngine

RAILS = ["3V3", "1V8", "2V5"]
N_IC = 4
DECAP_PER_IC = 24          # 96 decaps total
BUS = 12                   # inter-IC signal lines per hop


def build():
    nets = ["GND"] + RAILS
    comps, asn = [], []
    # IC chain U1..U4 (LQFP-100), each pad 1..100
    for k in range(1, N_IC + 1):
        comps.append(ComponentSpec("Package_QFP", "LQFP-100_14x14mm_P0.5mm",
                                   f"U{k}", value=f"IC{k}"))
    # two IO connectors (fixed)
    for j in (1, 2):
        comps.append(ComponentSpec("Connector_PinHeader_2.54mm",
                                   "PinHeader_2x06_P2.54mm_Vertical",
                                   f"J{j}", value="IO", fixed=True))
    # power pins on each IC (pad 99->first rail rotation, 100->GND)
    for k in range(1, N_IC + 1):
        asn.append(NetAssignment(f"U{k}", "99", RAILS[(k - 1) % len(RAILS)]))
        asn.append(NetAssignment(f"U{k}", "100", "GND"))
    # inter-IC signal buses: U_k pad p  <-> U_{k+1} pad p  via net BUSk_p
    pad = 1
    for k in range(1, N_IC):
        for b in range(BUS):
            net = f"B{k}_{b}"
            nets.append(net)
            asn.append(NetAssignment(f"U{k}", str(pad + b), net))
            asn.append(NetAssignment(f"U{k+1}", str(pad + b), net))
        pad += BUS
    # connector breakouts: J1/J2 pads -> U1/U4 spare pins
    for j, uk in ((1, 1), (2, N_IC)):
        for pin in range(1, 13):
            net = f"IO{j}_{pin}"
            nets.append(net)
            asn.append(NetAssignment(f"J{j}", str(pin), net))
            asn.append(NetAssignment(f"U{uk}", str(50 + pin), net))
    # decaps per IC across rails
    ci = 1
    for k in range(1, N_IC + 1):
        for d in range(DECAP_PER_IC):
            comps.append(ComponentSpec("Capacitor_SMD", "C_0402_1005Metric",
                                       f"C{ci}", value="100nF"))
            asn.append(NetAssignment(f"C{ci}", "1",
                                     RAILS[(d) % len(RAILS)]))
            asn.append(NetAssignment(f"C{ci}", "2", "GND"))
            ci += 1
    return DesignSpec(name="stress_big", category=BoardCategory.HIGH_SPEED,
                      nets=nets, components=comps, assignments=asn)


def main():
    spec = build()
    r = auto_design(spec, "/tmp/stress_big")
    res = DrcEngine().check(r.board_path)
    cats = Counter(v.rule for v in res.violations if v.severity == "error")
    rpct = r.routes_completed / r.routes_total * 100 if r.routes_total else 0
    print(f"parts={r.parts} nets={r.nets_count} layers={r.layers} "
          f"route={r.routes_completed}/{r.routes_total} ({rpct:.0f}%) "
          f"DRC={r.drc_errors} mfg={r.mfg_files}")
    print("unconnected_items:", cats.get("unconnected_items", 0))
    for k, v in cats.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
