#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成品板**逆向推演分析器** —— 从一份 .epro2(嘉立创社区开源成品)反推其整体设计。

道法自然·反者道之动:不臆造,从落库的真实记录里反读出设计者的全部意图——
层叠/板框/网络/电源树/器件 BOM/高速总线/36 页原理图功能划分。

输入:.epro2(zip,内含 .epru 设计字典 + IMAGE/)
输出:结构化设计情报报告(dict + 控制台摘要)。

.epru 行格式:  {head_json}||{payload_json}|
  head.type=="DOCHEAD" → 子文档边界(docType: FOOTPRINT/SYMBOL/DEVICE/SCH/SCH_PAGE/PCB/...)
  其余 head.type 为记录类型(COMPONENT/NET/PAD/VIA/WIRE/LAYER_PHYS/ATTR/...)
"""
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict


def _iter_records(epru_text):
    """逐行产出 (head, payload_str)。payload 可能很大,按需 json.loads。"""
    for ln in epru_text.split("\n"):
        ln = ln.strip()
        if not ln or "||" not in ln:
            continue
        h, p = ln.split("||", 1)
        if p.endswith("|"):
            p = p[:-1]
        try:
            head = json.loads(h)
        except Exception:
            continue
        yield head, p


def load_epru(epro2_path):
    z = zipfile.ZipFile(epro2_path)
    epru = [n for n in z.namelist() if n.endswith(".epru")][0]
    images = [n for n in z.namelist() if n.startswith("IMAGE/") and not n.endswith("/")]
    return z.read(epru).decode("utf-8", errors="ignore"), images


def _net_name(head):
    """NET 名藏在 head.id = '[\"NET\",\"<name>\"]'。"""
    try:
        v = json.loads(head.get("id", ""))
        if isinstance(v, list) and len(v) > 1:
            return v[1]
    except Exception:
        pass
    return ""


def classify_net(nm):
    u = nm.upper()
    if re.search(r"(DDR|DQ\d|DQS|BA\d|MA\d|ODT|MEMRST|DRAM|CKE)", u):
        return "DDR/memory"
    if re.search(r"(PCIE|PERP|PERN|PETP|PETN|REFCLK|PE_)", u):
        return "PCIe"
    if re.search(r"(USB|_DP|_DM|SSTX|SSRX|SSP|SSN)", u):
        return "USB"
    if re.search(r"(SATA|HDMI|TMDS|LVDS|RGMII|MDI|VGA|DISP|EDP)", u):
        return "display/highspeed-IO"
    if re.search(r"(VCC|VDD|VBAT|VSS|PWR|\+\d|V\d+P\d|_1P8|_3P3|_5V|VTT|VPP)", u):
        return "power"
    if re.search(r"GND", u):
        return "ground"
    if re.search(r"(XTAL|CLK|OSC|PLL)", u):
        return "clock"
    return "signal"


def _block_of(part_id):
    """从 partId 前缀推功能块,如 C_ADL_S_CPU_EXT_7.B -> CPU。"""
    u = (part_id or "").upper()
    for key, blk in [("CPU", "CPU"), ("DDR", "DDR"), ("PCIE", "PCIe"),
                     ("USB", "USB"), ("SATA", "SATA"), ("HDMI", "HDMI"),
                     ("VGA", "VGA"), ("PCH", "PCH/南桥"), ("PMIC", "电源"),
                     ("VRM", "VRM电源"), ("CLK", "时钟"), ("AUDIO", "音频")]:
        if key in u:
            return blk
    return "其他"


def analyze(epro2_path):
    epru, images = load_epru(epro2_path)
    try:
        z = zipfile.ZipFile(epro2_path)
        meta = json.loads(z.read("project2.json").decode("utf-8", "ignore"))
    except Exception:
        meta = {}

    docs = Counter()
    rec = Counter()
    cur_doctype = None

    nets = set()
    pcb_layer_phys = []
    footprint_values = Counter()   # ATTR key=Footprint -> qty
    designator_prefix = Counter()  # ATTR key=Designator 首字母段
    part_blocks = Counter()        # COMPONENT partId -> 功能块
    pcb_components = 0
    pad_count = via_count = wire_count = 0

    for head, p in _iter_records(epru):
        ty = head.get("type")
        if ty == "DOCHEAD":
            try:
                cur_doctype = json.loads(p).get("docType")
            except Exception:
                cur_doctype = None
            docs[cur_doctype] += 1
            continue
        rec[ty] += 1
        if ty == "NET" and cur_doctype == "PCB":
            nm = _net_name(head)
            if nm:
                nets.add(nm)
        elif ty == "LAYER_PHYS" and cur_doctype == "PCB":
            try:
                pcb_layer_phys.append(json.loads(p))
            except Exception:
                pass
        elif ty == "PAD":
            pad_count += 1
        elif ty == "VIA":
            via_count += 1
        elif ty == "WIRE":
            wire_count += 1
        elif ty == "COMPONENT":
            if cur_doctype == "PCB":
                pcb_components += 1
            try:
                pid = json.loads(p).get("partId", "")
                part_blocks[_block_of(pid)] += 1
            except Exception:
                pass
        elif ty == "ATTR":
            try:
                a = json.loads(p)
                k, v = a.get("key"), a.get("value")
                if k == "Footprint" and v:
                    footprint_values[v] += 1
                elif k == "Designator" and v:
                    m = re.match(r"[A-Za-z]+", str(v))
                    if m:
                        designator_prefix[m.group(0)] += 1
            except Exception:
                pass

    net_cls = Counter(classify_net(n) for n in nets)
    copper = [l for l in pcb_layer_phys
              if l.get("material") or (l.get("thickness") or 0) > 0
              or l.get("permittivity")]

    return {
        "file": epro2_path,
        "title": meta.get("title"),
        "tags": meta.get("tags"),
        "designer_note": (meta.get("introduction") or "")[:160],
        "epru_bytes": len(epru),
        "images": len(images),
        "docTypes": dict(docs),
        "counts": {
            "components_pcb": pcb_components,
            "nets_pcb_named": len(nets),
            "pads": pad_count,
            "vias": via_count,
            "wires": wire_count,
            "footprints": docs.get("FOOTPRINT", 0),
            "symbols": docs.get("SYMBOL", 0),
            "devices": docs.get("DEVICE", 0),
            "sch_pages": docs.get("SCH_PAGE", 0),
        },
        "pcb_layer_phys_records": len(pcb_layer_phys),
        "net_classes": dict(net_cls.most_common()),
        "functional_blocks_by_part": dict(part_blocks.most_common()),
        "designator_prefixes": dict(designator_prefix.most_common(20)),
        "top_footprints": dict(footprint_values.most_common(20)),
        "top_record_types": dict(rec.most_common(18)),
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "_x86.epro2"
    rep = analyze(path)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
