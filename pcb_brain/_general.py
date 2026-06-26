#!/usr/bin/env python3
"""
通用性测试台 — 证明引擎能吃 "不在 21 模板里" 的全新设计 (反者道之动)。

本设计 (ATtiny85 + 3×MOSFET 低边驱动 + 3×LED + ISP) 不属于任何内置模板,
用以暴露引擎对那 21 块板的过拟合点, 跑完整诚实流水线:
    spec/netlist → DNA → auto_layout → create_pcb → BFS布线(含铺铜) → DRC → 物理审计

两条通用通路都验证:
  A) 结构化 spec (dict)
  B) 标准 KiCad 网表 (.net) —— 任意原理图工具皆可导出

道法自然: 视全新设计能否端到端可制造, 为通用性之真值。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pcb_bootstrap as B  # noqa: E402,F401
from pcb_core import PCB  # noqa: E402
from _audit import audit  # noqa: E402

# 与 21 模板同一套诚实裁判 (web/build_site.py 亦用之), 保证通用性判定可比、可信
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kicad_origin.pcb.board import Board  # noqa: E402
from kicad_origin.engine.drc import run_drc  # noqa: E402
from kicad_origin.engine.quality import score_board  # noqa: E402

# ── 全新设计: ATtiny85 PWM RGB 驱动板 (21 模板里没有的 MCU + 拓扑) ──
SPEC = {
    "name": "attiny85_pwm_rgb",
    "description": "ATtiny85 + 3路低边MOSFET驱动RGB LED + ISP编程口 (通用性验证·非内置模板)",
    "board_size": [30, 30],
    "components": [
        {"ref": "U1", "value": "ATTINY85-20SU", "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "group": "mcu", "description": "主控MCU"},
        {"ref": "Q1", "value": "2N7002", "footprint": "Package_TO_SOT_SMD:SOT-23", "group": "passive", "description": "R通道低边开关"},
        {"ref": "Q2", "value": "2N7002", "footprint": "Package_TO_SOT_SMD:SOT-23", "group": "passive", "description": "G通道低边开关"},
        {"ref": "Q3", "value": "2N7002", "footprint": "Package_TO_SOT_SMD:SOT-23", "group": "passive", "description": "B通道低边开关"},
        {"ref": "D1", "value": "LED_R", "footprint": "LED_SMD:LED_0805_2012Metric", "group": "passive", "description": "红"},
        {"ref": "D2", "value": "LED_G", "footprint": "LED_SMD:LED_0805_2012Metric", "group": "passive", "description": "绿"},
        {"ref": "D3", "value": "LED_B", "footprint": "LED_SMD:LED_0805_2012Metric", "group": "passive", "description": "蓝"},
        {"ref": "R1", "value": "330", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "R限流"},
        {"ref": "R2", "value": "330", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "G限流"},
        {"ref": "R3", "value": "330", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "B限流"},
        {"ref": "R4", "value": "100", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "Q1栅极"},
        {"ref": "R5", "value": "100", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "Q2栅极"},
        {"ref": "R6", "value": "100", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "Q3栅极"},
        {"ref": "R7", "value": "10k", "footprint": "Resistor_SMD:R_0402_1005Metric", "group": "passive", "description": "RESET上拉"},
        {"ref": "C1", "value": "100nF", "footprint": "Capacitor_SMD:C_0402_1005Metric", "group": "passive", "description": "去耦"},
        {"ref": "C2", "value": "10uF", "footprint": "Capacitor_SMD:C_0805_2012Metric", "group": "passive", "description": "储能"},
        {"ref": "J1", "value": "PWR_5V", "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "group": "interface", "description": "5V电源"},
        {"ref": "J2", "value": "ISP", "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical", "group": "interface", "description": "ISP编程口"},
    ],
    # ATtiny85 SOIC-8: 1=PB5/RST 2=PB3 3=PB4 4=GND 5=PB0/MOSI 6=PB1/MISO 7=PB2/SCK 8=VCC
    # 2N7002 SOT-23:   1=G 2=S 3=D       LED 0805: 1=阳 2=阴       ISP 2x03: 1=MISO 2=VCC 3=SCK 4=MOSI 5=RST 6=GND
    "nets": {
        "VCC": [["U1", "8"], ["C1", "1"], ["C2", "1"], ["R1", "1"], ["R2", "1"], ["R3", "1"], ["R7", "1"], ["J1", "1"], ["J2", "2"]],
        "GND": [["U1", "4"], ["C1", "2"], ["C2", "2"], ["Q1", "2"], ["Q2", "2"], ["Q3", "2"], ["J1", "2"], ["J2", "6"]],
        "AR":  [["R1", "2"], ["D1", "1"]],
        "AG":  [["R2", "2"], ["D2", "1"]],
        "AB":  [["R3", "2"], ["D3", "1"]],
        "CR":  [["D1", "2"], ["Q1", "3"]],
        "CG":  [["D2", "2"], ["Q2", "3"]],
        "CB":  [["D3", "2"], ["Q3", "3"]],
        "PB0": [["U1", "5"], ["R4", "1"], ["J2", "4"]],
        "PB1": [["U1", "6"], ["R5", "1"], ["J2", "1"]],
        "PB4": [["U1", "3"], ["R6", "1"]],
        "PB2": [["U1", "7"], ["J2", "3"]],
        "GR":  [["R4", "2"], ["Q1", "1"]],
        "GG":  [["R5", "2"], ["Q2", "1"]],
        "GB":  [["R6", "2"], ["Q3", "1"]],
        "RST": [["U1", "1"], ["R7", "2"], ["J2", "5"]],
    },
}


def _emit_kicad_netlist(spec: dict) -> str:
    """从 spec 生成标准 KiCad (.net) 文本 — 证明 .net 通路可独立驱动引擎。"""
    lines = ['(export (version "E")', "  (components"]
    for c in spec["components"]:
        lines.append(
            f'    (comp (ref "{c["ref"]}") (value "{c["value"]}") '
            f'(footprint "{c["footprint"]}"))'
        )
    lines.append("  )")
    lines.append("  (nets")
    for i, (name, nodes) in enumerate(spec["nets"].items(), 1):
        lines.append(f'    (net (code "{i}") (name "{name}")')
        for ref, pin in nodes:
            lines.append(f'      (node (ref "{ref}") (pin "{pin}"))')
        lines.append("    )")
    lines.append("  )")
    lines.append(")")
    return "\n".join(lines)


def _report(tag: str, res: dict) -> int:
    if res.get("status") != "ok":
        print(f"[{tag}] FAILED: {res.get('error')}")
        return 1
    route = res.get("routing", {})
    pcb = res["pcb_path"]

    # 诚实裁判 (kicad_origin): DRC R001-R008 + 客观质量分 + 物理短路审计
    board = Board.load(pcb)
    rep = run_drc(board)
    q = score_board(board, res["name"], rep).to_dict()
    shorts, nvias, nsegs = audit(pcb)

    print(f"[{tag}] name={res['name']} comps={res['components']} nets={res['nets']}")
    print(f"        route engine={route.get('engine')} routed={route.get('routed')} "
          f"failed={route.get('failed', route.get('open'))} segs={nsegs} vias={nvias}")
    print(f"        DRC: errors={rep.error_count} warnings={rep.warning_count}")
    print(f"        quality: score={q['overall']} grade={q['grade']} "
          f"manufacturable={q['manufacturable']}")
    print(f"        physical audit (via/zone vs foreign copper): SHORTS={shorts}")
    print(f"        headline: {q['headline']}")
    if q.get("fix_list"):
        for fx in q["fix_list"]:
            print(f"          - {fx}")
    print(f"        pcb={pcb}")
    bad = (shorts > 0) or (rep.error_count > 0) or (not q["manufacturable"])
    print(f"        => {'OK (端到端可制造)' if not bad else '!! 通用路径暴露缺口'}")
    return 1 if bad else 0


def main() -> int:
    rc = 0

    # ── 通路 A: 结构化 spec dict ──
    print("=== A) spec dict → PCB ===")
    res_a = PCB.design_spec(SPEC, prefer_freerouting=False)
    rc |= _report("spec", res_a)

    # ── 通路 B: 标准 KiCad 网表 (.net) ──
    print("\n=== B) standard KiCad netlist (.net) → PCB ===")
    out = B.ensure_output_dir("attiny85_pwm_rgb_net")
    net_path = out / "attiny85_pwm_rgb.net"
    net_path.write_text(_emit_kicad_netlist(SPEC), encoding="utf-8")
    res_b = PCB.design_spec(str(net_path), output_dir=str(out), prefer_freerouting=False)
    rc |= _report("netlist", res_b)

    print(f"\n通用性测试台总判定: {'PASS' if rc == 0 else 'FAIL (见上方缺口, 待逐层修复)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
