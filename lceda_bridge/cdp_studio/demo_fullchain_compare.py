# -*- coding: utf-8 -*-
"""demo_fullchain_compare — 全链路「源 ↔ 克隆」无损比对(全程零 GUI)。

道法自然·取之尽锱铢:不止结构层 doc_counts 相等,更沿制造全链路逐层取证——
对**社区成品源**与其**底层克隆**各自导出 网表(.enet)/BOM(.xlsx)/Gerber(.zip)/
DSN(.dsn),解析其语义计数(器件数/网络数/层数/焊盘…)并逐项比对,证明
worker import 克隆在下游制造数据上同样无损。

用法:
    python demo_fullchain_compare.py [oshwhub_uuid]
默认靶子 = EDA-Pager(立创课程案例)。
"""
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d
import eda_flow
import reverse_analyze as ra
import demo_project_clone as dpc

EDA_PAGER = "d6f7528f939246efa27ed7e0ba022c6f"
OUT = "_cmp"


# --------------------------------------------------------------------------- #
# 导出文件的语义解析(用于比对,屏蔽时间戳/uuid/文件名差异)
# --------------------------------------------------------------------------- #
def parse_enet(b):
    """网表 .enet:统计器件(COMPONENT/部件行)与网络(NET)条目。"""
    t = b.decode("utf-8", "ignore")
    nets = set(re.findall(r'"?net(?:Name)?"?\s*[:=]\s*"([^"]+)"', t, re.I))
    if not nets:  # 退化:行式网表 (NET <name>)
        nets = set(re.findall(r'^\s*\(?NET\s+"?([^\s")]+)', t, re.M | re.I))
    comps = set(re.findall(r'"?(?:designator|refer?)"?\s*[:=]\s*"([A-Za-z]+\d+)"', t))
    return {"bytes": len(b), "nets": len(nets), "components": len(comps),
            "net_sample": sorted(nets)[:12]}


def parse_bom(b):
    """BOM .xlsx:解析 sharedStrings + sheet,统计数据行与去重位号。"""
    out = {"bytes": len(b), "rows": 0, "designators": 0}
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            shared = re.findall(r"<t[^>]*>(.*?)</t>", xml, re.S)
        sheet = ""
        for n in z.namelist():
            if re.match(r"xl/worksheets/sheet\d+\.xml", n):
                sheet = z.read(n).decode("utf-8", "ignore")
                break
        rows = re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S)
        out["rows"] = max(0, len(rows) - 1)  # 减表头
        desig = set()
        for cell in re.findall(r'<c[^>]*t="s"[^>]*><v>(\d+)</v>', sheet):
            i = int(cell)
            if i < len(shared):
                for tok in re.split(r"[,\s]+", shared[i]):
                    if re.fullmatch(r"[A-Za-z]+\d+", tok):
                        desig.add(tok)
        out["designators"] = len(desig)
    except Exception as e:
        out["err"] = str(e)[:120]
    return out


def parse_gerber(b):
    """Gerber .zip:层文件清单(屏蔽文件名内时间戳),按扩展名归类计数。"""
    out = {"bytes": len(b), "files": 0, "layers": {}}
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        names = [n for n in z.namelist() if not n.endswith("/")]
        out["files"] = len(names)
        ext = Counter()
        for n in names:
            base = os.path.basename(n)
            m = re.search(r"\.(G[A-Za-z0-9]+|gbr|drl|txt|drr?)$", base, re.I)
            ext[(m.group(1).upper() if m else os.path.splitext(base)[1] or base)] += 1
        out["layers"] = dict(sorted(ext.items()))
    except Exception as e:
        out["err"] = str(e)[:120]
    return out


# --------------------------------------------------------------------------- #
# 在一个已 open 的工程上,定位 PCB 文档并导出制造四件套
# --------------------------------------------------------------------------- #
def _first_pcb_uuid(f):
    for b in f.poll_boards():
        pcb = b.get("pcb")
        if isinstance(pcb, dict) and pcb.get("uuid"):
            return pcb["uuid"]
        if isinstance(pcb, list) and pcb:
            return pcb[0]["uuid"]
    return None


def export_suite(f, tag):
    """对当前 open 工程导出 netlist/bom/gerber/dsn,返回 {kind: parsed}。"""
    outdir = os.path.join(OUT, tag)
    pcb = _first_pcb_uuid(f)
    if not pcb:
        return {"err": "no pcb doc"}
    f.open_document(pcb, "pcb")
    time.sleep(2)
    res = {}
    grabbers = {
        "netlist": (f.export_netlist, parse_enet),
        "bom": (f.export_bom, parse_bom),
        "gerber": (f.export_gerber, parse_gerber),
        "dsn": (f.export_dsn, None),
    }
    for kind, (fn, parser) in grabbers.items():
        try:
            info = fn(outdir, name="%s_%s" % (tag, kind))
            with open(info["path"], "rb") as fh:
                raw = fh.read()
            res[kind] = {"path": info["path"], "size": info["size"]}
            if parser:
                res[kind].update(parser(raw))
        except Exception as e:
            res[kind] = {"err": str(e)[:160]}
    return res


def _cmp(a, b, keys):
    return {k: {"src": a.get(k), "clone": b.get(k), "eq": a.get(k) == b.get(k)}
            for k in keys}


def _norm_uuids(path):
    """把文件内所有 hex uuid 令牌(含 a_b 复合)按首现顺序规范化为 #N,
    屏蔽 import 的库 uuid 重映射 + 时间戳,便于做**语义**等价比对。"""
    t = open(path, encoding="utf-8", errors="ignore").read()
    seen, idx = {}, [0]

    def rep(m):
        k = m.group(0)
        if k not in seen:
            seen[k] = "#%d" % idx[0]
            idx[0] += 1
        return seen[k]

    return re.sub(r"[0-9a-f]{8,32}(?:_[0-9a-f]{8,32})*", rep, t)


def netlist_semantic_identical(src_enet, clone_enet):
    """网表语义等价:uuid 规范化后逐字节相同 ⇒ 仅库 uuid 重映射差异,无设计丢失。"""
    try:
        return _norm_uuids(src_enet) == _norm_uuids(clone_enet)
    except Exception:
        return None


def run(src_uuid=EDA_PAGER):
    os.makedirs(OUT, exist_ok=True)
    report = {"src_uuid": src_uuid, "ts": int(time.time())}

    # 0) 源设计真值(离线 .epru 逆向) -----------------------------------------
    f = eda_flow.Flow()
    ws = f.ws
    src_bytes, _ = dpc.download_epro2(ws, src_uuid)
    src_epru = dpc.epru_text(src_bytes)
    report["src_live_docs"] = dpc.doc_counts(src_epru, live_only=True)
    # reverse_analyze.analyze 吃路径,落盘后调用
    src_path = os.path.join(OUT, "_src.epro2")
    with open(src_path, "wb") as fh:
        fh.write(src_bytes)
    report["src_intel"] = ra.analyze(src_path)["counts"]

    # 1) 源工程在编辑器中打开 → 导出制造四件套 -------------------------------
    print(">> 打开社区源工程并导出...")
    try:
        f.open_project(src_uuid)
        report["src_export"] = export_suite(f, "src")
    except Exception as e:
        report["src_export"] = {"err": "open/export src 失败: %s" % (str(e)[:160])}

    # 2) 底层克隆该源 → 导出制造四件套 ---------------------------------------
    print(">> 底层克隆源工程...")
    cl = dpc.run(src_uuid, clone_name="DAO_CMP_%d" % int(time.time()))
    report["clone_uuid"] = cl["clone"]
    report["clone_live_docs"] = cl["clone_live"]
    report["clone_exact"] = cl["exact"]
    print(">> 打开克隆并导出...")
    f2 = eda_flow.Flow()
    f2.open_project(cl["clone"])
    report["clone_export"] = export_suite(f2, "clone")

    # 3) 逐层比对 ------------------------------------------------------------
    se, ce = report.get("src_export", {}), report.get("clone_export", {})
    diff = {}
    if isinstance(se.get("netlist"), dict) and isinstance(ce.get("netlist"), dict):
        diff["netlist"] = _cmp(se["netlist"], ce["netlist"], ["nets", "components"])
        if se["netlist"].get("path") and ce["netlist"].get("path"):
            sem = netlist_semantic_identical(se["netlist"]["path"], ce["netlist"]["path"])
            diff["netlist"]["semantic_identical"] = {"src": True, "clone": sem, "eq": bool(sem)}
    if isinstance(se.get("bom"), dict) and isinstance(ce.get("bom"), dict):
        diff["bom"] = _cmp(se["bom"], ce["bom"], ["rows", "designators"])
    if isinstance(se.get("gerber"), dict) and isinstance(ce.get("gerber"), dict):
        diff["gerber"] = _cmp(se["gerber"], ce["gerber"], ["files", "layers"])
    report["diff"] = diff
    report["lossless"] = bool(diff) and all(
        v.get("eq") for fam in diff.values() for v in fam.values())
    return report


if __name__ == "__main__":
    rep = run(sys.argv[1] if len(sys.argv) > 1 else EDA_PAGER)
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
