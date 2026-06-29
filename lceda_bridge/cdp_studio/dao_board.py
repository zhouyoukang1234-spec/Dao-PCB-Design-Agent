# -*- coding: utf-8 -*-
"""dao_board —— 声明式建板引擎(正本清源·重写)。

历史:旧版本 `dao_board.py` 是从某次会话截断落库的**残片**(从 `route_export`
方法中段起、文件尾部断行),既缺类头/`BoardSpec`/`BoardBuilder` 定义,又调用了
一批 `eda_flow` 早已重构掉的方法(`auto_board_outline`/`reload_and_reopen`/
`prepare_pcb_nets`/`create_diff_pair`/`autoroute_gui`/`widen_net_tracks`/
`auto_ground_pour`/`drc_check`/`export_all`)→ 连导入都会失败,拖垮 6 个 `build_*`
脚本与 CI 的 py_compile。

本次重写:把声明式引擎重建在**已活体验证的当前底座**之上(`scaffold` /
`place_device_det` / `auto_route` / `sync_to_pcb` / `board_outline` / `drc` /
`export_*`)。对当前 `eda_flow` 尚未提供的可选特性(覆铜/差分对/线宽),不再硬调
不存在的方法,而是**探测存在即用、否则在报告里诚实标注 unsupported**,使携带这些
字段的 spec 也能跑通主链而不崩。

用法(单文件即可):
    from dao_board import BoardSpec, BoardBuilder
    b = BoardBuilder()
    b.build(SPEC)                  # 全链:scaffold→place→wire→sync→route_export
    REUSE=1 python build_xxx.py    # 复用编辑器当前已打开的 board(本会话实证用)
"""
import os
import time
from dataclasses import dataclass, field

import eda_flow


@dataclass
class BoardSpec:
    """一块板的声明式描述。

    parts: [(designator, device_query, (x, y)), ...]
        device_query 交给 `search_device` 解析(取首个命中);(x, y) 为原理图数据坐标。
    nets:  {net_name: [(designator, pin), ...], ...}
        引脚以 (器件位号, 引脚号) 表述,wire 阶段映射到 primitiveId 后交 auto_route。
    可选: introduction / ground_pour / net_widths{net: mil} / diff_pairs[(name, pos, neg)]
    """
    name: str
    parts: list
    nets: dict
    introduction: str = ""
    ground_pour: bool = False
    net_widths: dict = field(default_factory=dict)
    diff_pairs: list = field(default_factory=list)


def _group_by_width(widths):
    """{net: mil} → 按线宽聚合的 [(mil, [net, ...]), ...](升序)。"""
    g = {}
    for net, mil in (widths or {}).items():
        g.setdefault(mil, []).append(net)
    return sorted(g.items())


class BoardBuilder:
    """声明式建板引擎:把 BoardSpec 编译为一串确定性底层 RPC。"""

    def __init__(self):
        self.eda = eda_flow.Flow()
        self.state = {}
        self._pids = {}
        self._ground_pour = False
        self._net_widths = {}
        self._diff_pairs = []

    # ----------------------------------------------------------- 句柄 #
    def scaffold(self, spec, reuse=None):
        """建工程(或 REUSE=1 复用已打开 board),取 project/pcb/sch_page 句柄。

        返回含 "project"/"pcb"/"sch_page" 三键的 state(被 build_* 直接索引)。
        """
        if reuse is None:
            reuse = os.environ.get("REUSE") == "1"
        f = self.eda
        if reuse:
            b = f.poll_boards()
            if not b:
                raise eda_flow.FlowError("REUSE=1 但编辑器无已打开 board")
            f.board = b[0]
            h = {
                "project": f.board["uuid"],
                "pcb": f.board["pcb"]["uuid"],
                "page": f.board["schematic"]["page"][0]["uuid"],
            }
        else:
            s = f.scaffold(spec.name)
            h = {"project": s["project"], "pcb": s["pcb"], "page": s["page"]}
        self.state = {
            "name": spec.name,
            "project": h["project"],
            "pcb": h["pcb"],
            "sch_page": h["page"],
        }
        return self.state

    # ----------------------------------------------------------- 放件 #
    def place(self, spec):
        f = self.eda
        if not self.state:
            self.scaffold(spec)
        f.open_document(self.state["sch_page"], kind="sch")
        time.sleep(2)
        f.clear_sch_parts()
        f.save_sch()
        time.sleep(1)
        self._pids = {}
        placed = {}
        for des, query, (x, y) in spec.parts:
            hits = f.search_device(query)
            if not hits:
                raise eda_flow.FlowError("器件未找到: %s (%s)" % (query, des))
            d0 = hits[0]
            device = {"uuid": d0["uuid"], "libraryUuid": d0["libraryUuid"], "name": d0.get("name")}
            pid = f.place_device_det(device, x, y, designator=des)
            self._pids[des] = pid
            placed[des] = {"pid": pid, "query": query, "xy": [x, y]}
        f.save_sch()
        time.sleep(1)
        return placed

    def _resolve_pids(self):
        """单独跑 wire 阶段(未经本进程 place)时,从当前原理图回建 位号→pid。"""
        if self._pids:
            return
        for pid in self.eda.parts():
            info = self.eda.part_info(pid) or {}
            des = info.get("designator") or info.get("name")
            if des:
                self._pids[des] = pid

    # ----------------------------------------------------------- 连线 #
    def wire(self, spec):
        f = self.eda
        self._resolve_pids()
        net_map = {}
        skipped = {}
        for net, members in spec.nets.items():
            terminals = []
            for des, pin in members:
                if des in self._pids:
                    terminals.append((self._pids[des], pin))
                else:
                    skipped.setdefault(net, []).append(des)
            if terminals:
                net_map[net] = terminals
        lanes = f.auto_route(net_map)
        f.save_sch()
        time.sleep(1)
        out = {"lanes": lanes}
        if skipped:
            out["skipped_missing_part"] = skipped
        return out

    # ----------------------------------------------------------- 同步 #
    def sync(self, spec):
        return self.eda.sync_to_pcb(self.state["pcb"])

    # ----------------------------------------------- 板框/规则/导出 #
    def _maybe(self, method_name, *args, **kwargs):
        """探测当前 eda_flow 是否提供某可选能力:有则调用,无则标注 unsupported。"""
        fn = getattr(self.eda, method_name, None)
        if not callable(fn):
            return {"unsupported": method_name}
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"err": str(e)[:80]}

    def route_export(self, out_base=None, margin=60):
        f = self.eda
        f.open_document(self.state["pcb"], kind="pcb")
        time.sleep(2)
        outline = {"existing": True} if f.has_board_outline() else f.board_outline(margin=margin)
        self._maybe("save_pcb", self.state["pcb"])
        time.sleep(1)

        # 可选特性:存在即用,否则诚实标注(当前底座未实现差分对/线宽/覆铜)。
        diff = None
        if self._diff_pairs:
            diff = {nm: self._maybe("create_diff_pair", nm, pos, neg)
                    for nm, pos, neg in self._diff_pairs}
        widened = None
        if self._net_widths:
            widened = {str(mil): self._maybe("widen_net_tracks", mil, grp)
                       for mil, grp in _group_by_width(self._net_widths)}
        pour = self._maybe("auto_ground_pour", net="GND", layers=(1, 2)) if self._ground_pour else None

        nets = f.pcb_nets()
        try:
            drc = f.drc(timeout=120)
        except Exception as e:
            drc = "ERR:" + str(e)[:60]

        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               (out_base or self.state.get("name", "Dao")) + "_fab")
        exporters = {"gerber": f.export_gerber, "bom": f.export_bom,
                     "pnp": f.export_pnp, "netlist": f.export_netlist}
        exp = {}
        for k, fn in exporters.items():
            try:
                r = fn(out_dir)
                exp[k] = r.get("size") if isinstance(r, dict) else r
            except Exception as e:
                exp[k] = "ERR:" + str(e)[:60]
        return {"outline": outline, "diff": diff, "widened": widened, "pour": pour,
                "nets": nets, "drc": drc, "export_dir": out_dir, "export": exp}

    # ----------------------------------------------------- 一键全流程 #
    def build(self, spec, margin=60):
        self._ground_pour = getattr(spec, "ground_pour", False)
        self._net_widths = getattr(spec, "net_widths", {})
        self._diff_pairs = getattr(spec, "diff_pairs", [])
        report = {"spec": spec.name}
        report["scaffold"] = {k: self.scaffold(spec)[k] for k in ("project", "pcb", "sch_page")}
        report["place"] = self.place(spec)
        report["wire"] = self.wire(spec)
        report["sync"] = self.sync(spec)
        report["route_export"] = self.route_export(out_base=spec.name, margin=margin)
        return report
