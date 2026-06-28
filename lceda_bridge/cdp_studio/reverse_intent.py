#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设计**本源逆推器** —— 从一份成品 .epro2 反推「最初的念头 → 原理图 → 布局布线 → 制造产出」全链路。

道法自然·反者道之动:reverse_analyze 给出"有什么"(计数/分类);本模块再进一步反推
"为什么这么设计"——从落库的真实连通性(PAD_NET 网表)反读出:
  · 本源念头(inferred intent):这块板到底想做成什么。
  · 电源树(power tree):按真实扇出排出供电骨架(输入轨 → 稳压 → 各域轨)。
  · 接口盘点(interface inventory):USB/PCIe/DDR/显示等高速总线规模 + 差分对。
  · 连通枢纽(hubs):按连接网络度数反推核心 IC / 大连接器。
  · 功能分块(functional pages):原理图分页 → 各页器件规模(设计者的心智划分)。
  · 全链路阶段溯源(provenance):每个阶段(概念/原理图/布局/制造)的可复原证据与置信度。
  · 系统缺陷自暴露(gaps):本系统在该真实工程上**没能**复原的内容,诚实列出,驱动改进。

只读 .epru,不臆造;所有结论都附带支撑证据(计数)。
"""
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reverse_analyze as ra


# 输入级供电轨(电池/适配器/总线直供),与板内稳压后的域轨区分
_INPUT_RAIL = re.compile(
    r"(VBAT|VBUS|VIN|DC[_ ]?IN|\+?1[2-9]V|\+?2[0-9]V|ADAPTER|DCIN|BAT\b|USB5V|VCC5)",
    re.I)

# 控制/状态网络后缀:名字带电压但实为使能/反馈/电源好信号,不是供电轨,须排除
_CTRL_SUFFIX = re.compile(
    r"(_EN|_CTRL|_PG|_PWRGD|_PWROK|_GOOD|_OK|_SEL|_FLT|_FAULT|_GATE|_SET|"
    r"_ADJ|_FB|_SENSE|_SNS|_DET|_RST|_SHDN|_TRIP)\b", re.I)


def _is_power_name(nm):
    """供电轨命名判定(补 classify_net 漏掉的 3.3V/1V8/5V0/12V 等无前导+写法)。

    诚实边界:名字含电压但带 _EN/_CTRL/_PG 等控制后缀的是控制/状态网,排除之。
    """
    u = (nm or "").upper()
    if not u or _CTRL_SUFFIX.search(u):
        return False
    if ra.classify_net(u) == "power":
        return True
    # 形如 3.3V / 5V / 1V8 / 0V9 / 12V / 5V0 / +3V3 / VDD_xxx / AVDD / DVDD
    if re.search(r"^\+?\d+(?:[.\_]?\d+)?V(?:\d+)?(?:_|$|[A-Z0-9])", u):
        return True
    if re.search(r"(A?D?VDD|AVCC|DVCC|VTT|VPP|VREF|VPH|VSYS|VOUT|VMAIN)", u):
        return True
    return False


def _net_token(nm):
    """网络名 → 功能 token:取首个字母语义段,过滤电源/地/匿名($1N..)/通用单字母。"""
    u = (nm or "").upper()
    if not u or u.startswith("$") or ra.classify_net(u) in ("power", "ground"):
        return None
    m = re.match(r"[A-Z][A-Z]+", u)         # 至少两字母,避免 R/D 等无意义
    if not m:
        return None
    tok = m.group(0)
    if tok in ("NET", "NETLABEL", "PIN", "VCC", "GND", "VDD"):
        return None
    return tok


def _functional_clusters(net_comps, comp_desig, comp_partid):
    """从 net->components 连通性把器件按功能 token 聚类(页名通用时的功能分块反推)。"""
    tok_comps = defaultdict(set)           # token -> {compUuid}
    tok_nets = Counter()                   # token -> 网络数
    comp_tok_hits = defaultdict(Counter)   # compUuid -> token -> 命中次数
    for nm, comps in net_comps.items():
        tok = _net_token(nm)
        if not tok:
            continue
        tok_nets[tok] += 1
        for cu in comps:
            comp_tok_hits[cu][tok] += 1
    # 每个器件归入它连得最多的 token
    for cu, hits in comp_tok_hits.items():
        best = hits.most_common(1)[0][0]
        tok_comps[best].add(cu)
    out = []
    for tok, comps in sorted(tok_comps.items(), key=lambda kv: -len(kv[1])):
        if tok_nets[tok] < 2 and len(comps) < 2:
            continue
        members = sorted(comp_desig.get(c) or comp_partid.get(c) or c[:8] for c in comps)
        out.append({"block": tok, "nets": tok_nets[tok],
                    "components": len(comps), "members": members[:12]})
    return out[:18]


def _rail_kind(nm, fanout, max_fanout):
    if _INPUT_RAIL.search(nm or ""):
        return "input"          # 板外输入/电池/总线直供
    if fanout >= max(8, max_fanout * 0.4):
        return "backbone"       # 主干域轨(高扇出)
    return "domain"             # 局部域轨


def reconstruct(epro2_path):
    epru, images = ra.load_epru(epro2_path)
    try:
        z = zipfile.ZipFile(epro2_path)
        meta = json.loads(z.read("project2.json").decode("utf-8", "ignore"))
    except Exception:
        meta = {}

    cur = None
    cur_doc_uuid = None
    comp_partid = {}                    # compUuid -> partId
    comp_desig = {}                     # PCB compUuid -> Designator(R17/U3/...)
    comp_device = {}                    # PCB compUuid -> device uuid
    net_fanout = Counter()              # padNet -> PAD_NET 计数(真实扇出)
    net_comps = defaultdict(set)        # net -> {compUuid}
    comp_nets = defaultdict(set)        # compUuid -> {net}
    diff_nets = set()                   # 差分网络名
    sch_pages = []                      # [(uuid,title)]
    page_comp = Counter()              # sch_page uuid -> COMPONENT 计数
    layer_phys = []
    doc_titles = {}                     # uuid -> META.title(供页名展示)

    for head, p in ra._iter_records(epru):
        ty = head.get("type")
        if ty == "DOCHEAD":
            try:
                pj = json.loads(p)
                cur = pj.get("docType"); cur_doc_uuid = pj.get("uuid")
            except Exception:
                cur, cur_doc_uuid = None, None
            continue
        if ty == "META":
            try:
                m = json.loads(p)
                if cur_doc_uuid:
                    doc_titles[cur_doc_uuid] = m.get("title")
                if cur == "SCH_PAGE":
                    sch_pages.append((cur_doc_uuid, m.get("title")))
            except Exception:
                pass
        elif ty == "COMPONENT":
            cid = head.get("id")
            try:
                pid = json.loads(p).get("partId", "")
            except Exception:
                pid = ""
            if cid and pid and cid not in comp_partid:
                comp_partid[cid] = pid
            if cur == "SCH_PAGE" and cur_doc_uuid:
                page_comp[cur_doc_uuid] += 1
        elif ty == "PAD_NET" and cur == "PCB":
            try:
                nm = json.loads(p).get("padNet") or ""
            except Exception:
                nm = ""
            if not nm:
                continue
            net_fanout[nm] += 1
            # id = ["PAD_NET", compUuid, padNum, ...]
            try:
                idv = json.loads(head.get("id", "[]"))
                if isinstance(idv, list) and len(idv) > 1:
                    cu = idv[1]
                    net_comps[nm].add(cu)
                    comp_nets[cu].add(nm)
            except Exception:
                pass
        elif ty == "NET" and cur == "PCB":
            nm = ra._net_name(head)
            try:
                if json.loads(p).get("differentialName"):
                    diff_nets.add(nm)
            except Exception:
                pass
        elif ty == "ATTR" and cur == "PCB":
            try:
                a = json.loads(p)
                pid, k, v = a.get("parentId"), a.get("key"), a.get("value")
                if pid and v:
                    if k == "Designator":
                        comp_desig[pid] = v
                    elif k == "Device":
                        comp_device[pid] = v
            except Exception:
                pass
        elif ty == "LAYER_PHYS" and cur == "PCB":
            try:
                layer_phys.append(json.loads(p))
            except Exception:
                pass

    # ---- 电源树 ----
    power = {nm: c for nm, c in net_fanout.items() if _is_power_name(nm)}
    grounds = {nm: c for nm, c in net_fanout.items() if ra.classify_net(nm) == "ground"}
    max_pf = max(power.values()) if power else 0
    rails = [{"rail": nm, "fanout": c, "kind": _rail_kind(nm, c, max_pf)}
             for nm, c in sorted(power.items(), key=lambda kv: -kv[1])]

    # ---- 接口盘点 ----
    iface = Counter()
    for nm in net_fanout:
        cls = ra.classify_net(nm)
        if cls in ("USB", "PCIe", "DDR/memory", "display/highspeed-IO", "clock"):
            iface[cls] += 1

    # ---- 连通枢纽(按连接的去重网络数排名;解析 designator + 器件名 → 反推核心 IC)----
    hubs = []
    for cu, nets in sorted(comp_nets.items(), key=lambda kv: -len(kv[1]))[:15]:
        desig = comp_desig.get(cu)
        dev_title = doc_titles.get(comp_device.get(cu, ""))
        hubs.append({"designator": desig or "?",
                     "device": dev_title or comp_partid.get(cu) or "?",
                     "net_degree": len(nets), "comp": cu[:10]})
    named_hubs = sum(1 for h in hubs if h["designator"] != "?")

    # ---- 功能分块(原理图分页) ----
    pages = [{"title": (t or "(未命名)"), "components": page_comp.get(u, 0)}
             for u, t in sch_pages]
    pages.sort(key=lambda d: -d["components"])
    page_titles = [t for _, t in sch_pages if t]
    generic_pages = all(re.fullmatch(r"P\d+|Sheet\d*|Page\d*|页\d*", (t or ""), re.I)
                        for t in page_titles) if page_titles else True

    # ---- 按连通性自动功能聚类(页名通用时仍能反推功能块) ----
    # 取每个网络名的语义前缀 token(USIM0_PWR->USIM, LTE_BOOT->LTE, BT_MID->BT),
    # 据 net->components 把器件归入它连得最多的功能 token,从纯连通性重建功能分块。
    clusters = _functional_clusters(net_comps, comp_desig, comp_partid)

    # ---- 本源念头(从主导功能 + 接口规模反推) ----
    net_cls = Counter(ra.classify_net(n) for n in net_fanout)
    dominant = [c for c, _ in net_cls.most_common() if c not in ("signal", "ground")][:4]
    intent_bits = []
    if iface.get("DDR/memory"):
        intent_bits.append("带 DDR 内存子系统")
    if iface.get("PCIe"):
        intent_bits.append("PCIe 扩展")
    if iface.get("USB"):
        intent_bits.append("USB 接口")
    if iface.get("display/highspeed-IO"):
        intent_bits.append("显示/高速 IO")
    rail_kinds = Counter(r["kind"] for r in rails)
    intent = {
        "title": meta.get("title"),
        "tags": meta.get("tags"),
        "designer_note": (meta.get("introduction") or "")[:200],
        "dominant_domains": dominant,
        "inferred_purpose": "；".join(intent_bits) or "通用功能板(无显著高速总线)",
        "power_complexity": "%d 路供电轨(输入%d/主干%d/域%d)" % (
            len(rails), rail_kinds.get("input", 0),
            rail_kinds.get("backbone", 0), rail_kinds.get("domain", 0)),
    }

    # ---- 全链路阶段溯源 ----
    copper = [l for l in layer_phys
              if l.get("material") or (l.get("thickness") or 0) > 0 or l.get("permittivity")]
    stages = [
        {"stage": "1.概念/需求", "evidence": "title/tags/introduction",
         "recoverable": bool(meta.get("title")),
         "confidence": "高" if meta.get("introduction") else "中(仅标题)"},
        {"stage": "2.原理图", "evidence": "SCH_PAGE×%d / 器件按页分布" % len(sch_pages),
         "recoverable": len(sch_pages) > 0,
         "confidence": "低(页名通用,功能分块靠推断)" if generic_pages else "高(页名即功能块)"},
        {"stage": "3.网表/连通", "evidence": "PAD_NET 真实扇出 %d 网络" % len(net_fanout),
         "recoverable": len(net_fanout) > 0, "confidence": "高"},
        {"stage": "4.布局布线", "evidence": "铜层 %d / 过孔 / 走线" % len(copper),
         "recoverable": len(layer_phys) > 0, "confidence": "高"},
        {"stage": "5.制造产出", "evidence": "层叠/板框/钻孔(可程序化导出 Gerber/BOM)",
         "recoverable": len(copper) > 0, "confidence": "高"},
    ]

    # ---- 系统缺陷自暴露 ----
    gaps = []
    if generic_pages and len(sch_pages) > 1 and not clusters:
        gaps.append("原理图页名通用(P1/Sheet…)且网络名无语义 token,功能分块无法重建——"
                    "连通性聚类与页名俱失效。")
    miscls = [nm for nm in net_fanout
              if _is_power_name(nm) and ra.classify_net(nm) != "power"]
    if miscls:
        gaps.append("classify_net 漏判 %d 个供电网络(如 %s)——已在 _is_power_name 兜底,"
                    "建议回灌主分类器。" % (len(miscls), ", ".join(sorted(set(miscls))[:6])))
    if hubs and named_hubs == 0:
        gaps.append("PAD_NET.compUuid 未能映射到 designator——跨文档器件引用解析缺口。")
    if not diff_nets:
        gaps.append("未解析到差分对(differentialName 空或本板无高速差分)——差分组重建待验证。")

    return {
        "file": epro2_path,
        "intent": intent,
        "power_tree": {"rails": rails[:24], "rail_total": len(rails),
                       "grounds": sorted(grounds.items(), key=lambda kv: -kv[1])[:4]},
        "interfaces": dict(iface.most_common()),
        "differential_pairs": len(diff_nets),
        "connectivity_hubs": hubs,
        "functional_pages": pages[:20],
        "functional_clusters": clusters,
        "provenance_stages": stages,
        "gaps": gaps,
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "_cmp/_src.epro2"
    rep = reconstruct(path)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
