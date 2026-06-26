"""
quality — 客观 PCB 质量评分引擎 (闭环最后一环)

> "知人者智, 自知者明." — 一块板好不好, 不该靠人的水平来评,
> 该靠可复现的客观度量来评。本引擎把"难以评判的 PCB 优劣"压成
> 一张任何人都看得懂的评分卡: 6 个维度各 0-100, 加权得总分与等级,
> 并给出精确的"还差什么"缺陷清单 + 是否可制造的硬判定。

度量全部从 **真实板几何 + 诚实 DRC** 反演 (不读任何自述字段):

  连通完整性 connectivity   (权重 30) — 多脚网中真正全连通的占比 (R008 反演)
  短路安全   shorts         (权重 25) — 硬短路数 (R001/R005/R007-error), 一处即重罚
  间距余量   clearance      (权重 12) — 走线-走线/走线-焊盘间距不足占比 (R007-warn/R006)
  可制造性   dfm            (权重 13) — 线宽/孔径/环宽 vs 工艺能力 (JLCPCB 标准)
  电源地完整 power          (权重 12) — GND 铺铜覆盖率 + 去耦电容 + 电源网连通
  布局与规则 placement      (权重  8) — 元件不出板/不重号 + 板面利用率合理

行业基准 (JLCPCB/嘉立创 标准 2 层工艺, 也是 IPC-2221 推荐下限附近):
  最小线宽/线距 0.127mm (5mil) — 取保守 0.15mm
  最小过孔孔径   0.2mm,  过孔外径 0.4mm  → 环宽 0.1mm
  最小钻孔间距   0.5mm
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from kicad_origin.pcb.board import Board
from kicad_origin.engine.drc import DRCReport, run_drc


# ── 工艺能力基准 (JLCPCB 标准 2 层) ──
FAB_MIN_TRACE_MM   = 0.15    # 最小线宽
FAB_MIN_CLEAR_MM   = 0.15    # 最小线距
FAB_MIN_VIA_DRILL  = 0.20    # 最小过孔孔径
FAB_MIN_VIA_ANNULAR = 0.10   # 过孔最小环宽 (外径-孔)/2
FAB_MIN_PAD_ANNULAR = 0.13   # THT 焊盘最小环宽
GND_TARGET_COVERAGE = 0.40   # 接地铺铜目标覆盖率 (达到即满分)

# ── 维度权重 ──
WEIGHTS = {
    "connectivity": 30,
    "shorts":       25,
    "clearance":    12,
    "dfm":          13,
    "power":        12,
    "placement":     8,
}

GROUND_TOKENS = ("GND", "GROUND", "VSS", "AGND", "DGND", "PGND", "EARTH")
POWER_TOKENS  = ("VCC", "VDD", "3V3", "3.3V", "5V", "1V8", "1.8V", "VIN",
                 "VBAT", "VBUS", "VDDA", "VVCC", "12V", "VOUT", "VPP")


@dataclass
class Dimension:
    """单个质量维度的得分与依据。"""
    key:     str
    label:   str
    score:   float                       # 0-100
    weight:  float
    detail:  str = ""
    issues:  List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label,
                "score": round(self.score, 1), "weight": self.weight,
                "detail": self.detail, "issues": self.issues}


@dataclass
class QualityScore:
    """整板质量评分卡。"""
    board_name:     str
    overall:        float                 # 0-100 加权总分
    grade:          str                   # A/B/C/D/F
    manufacturable: bool                  # 无短路且无开路 = 可制造
    dimensions:     List[Dimension]
    headline:       str                   # 一句话客观结论
    fix_list:       List[str]             # 按优先级排序的"还差什么"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "board_name":     self.board_name,
            "overall":        round(self.overall, 1),
            "grade":          self.grade,
            "manufacturable": self.manufacturable,
            "headline":       self.headline,
            "dimensions":     [d.to_dict() for d in self.dimensions],
            "fix_list":       self.fix_list,
        }


# ─────────────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────────────
def _is_ground(name: str) -> bool:
    u = (name or "").upper()
    return any(t in u for t in GROUND_TOKENS)


def _is_power(name: str) -> bool:
    u = (name or "").upper()
    if _is_ground(u):
        return False
    return any(t in u for t in POWER_TOKENS)


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _board_area(board: Board) -> float:
    bo = board.board_outline()
    if bo and not bo.empty:
        return max(1.0, bo.width * bo.height)
    bb = board.bbox()
    if not bb.empty:
        return max(1.0, bb.width * bb.height)
    return 1.0


def _zone_area_by_net(board: Board) -> Dict[int, float]:
    """每个 net 的铺铜近似面积 (各 filled_polygon 包围盒面积之和, mm²)。"""
    out: Dict[int, float] = {}
    for z in board.zones():
        n = z.net
        if n <= 0:
            continue
        a = 0.0
        for poly in z.filled_polygon_points():
            if len(poly) < 3:
                continue
            xs = [p.x for p in poly]
            ys = [p.y for p in poly]
            a += (max(xs) - min(xs)) * (max(ys) - min(ys))
        out[n] = out.get(n, 0.0) + a
    return out


# ─────────────────────────────────────────────────────────────────────
# 各维度评分
# ─────────────────────────────────────────────────────────────────────
def _dim_connectivity(board: Board, rep: DRCReport) -> Dimension:
    """多脚网真正全连通的占比 (R008 开路反演)。"""
    net_pads: Dict[int, int] = {}
    for fp in board.footprints():
        for pad in fp.pads():
            n = pad.net_number
            if n > 0:
                net_pads[n] = net_pads.get(n, 0) + 1
    multi = [n for n, c in net_pads.items() if c >= 2]
    total = len(multi)
    open_nets = sorted({
        v.extra.get("net_number") for v in rep.violations
        if v.rule == "R008" and v.severity == "error"
    } - {None})
    n_open = len(open_nets)
    names = {n.number: n.name for n in board.nets()}
    if total == 0:
        return Dimension("connectivity", "连通完整性", 100.0,
                         WEIGHTS["connectivity"], "无多脚网络")
    connected = total - n_open
    score = 100.0 * connected / total
    detail = f"{connected}/{total} 多脚网全连通"
    issues = []
    if n_open:
        shown = ", ".join(names.get(n, f"#{n}") for n in open_nets[:8])
        more = f" 等 {n_open} 条" if n_open > 8 else ""
        issues.append(f"{n_open} 条网络未连通(开路): {shown}{more}")
    return Dimension("connectivity", "连通完整性", score,
                     WEIGHTS["connectivity"], detail, issues)


def _dim_shorts(board: Board, rep: DRCReport) -> Dimension:
    """硬短路数 — 一处即不可制造, 指数重罚。"""
    short_rules = {"R001", "R005", "R007"}
    shorts = [v for v in rep.violations
              if v.rule in short_rules and v.severity == "error"]
    n = len(shorts)
    if n == 0:
        return Dimension("shorts", "短路安全", 100.0, WEIGHTS["shorts"],
                         "无任何硬短路")
    score = 100.0 * (0.5 ** n)
    issues = [v.message for v in shorts[:6]]
    if n > 6:
        issues.append(f"... 共 {n} 处硬短路")
    return Dimension("shorts", "短路安全", score, WEIGHTS["shorts"],
                     f"{n} 处硬短路", issues)


def _dim_clearance(board: Board, rep: DRCReport) -> Dimension:
    """走线间距不足占比 (R007-warn) + 钻孔间距 (R006)。"""
    warns = [v for v in rep.violations
             if v.rule in ("R007", "R006") and v.severity == "warning"]
    n = len(warns)
    seg = max(1, len(board.segments()))
    ratio = n / seg
    score = 100.0 * max(0.0, 1.0 - min(1.0, ratio * 2.0))
    issues = []
    if n:
        issues.append(f"{n} 处间距不足(可制造但偏紧, 占走线 {ratio*100:.0f}%)")
    return Dimension("clearance", "间距余量", score, WEIGHTS["clearance"],
                     f"{n} 处间距不足 / {seg} 走线", issues)


def _dim_dfm(board: Board) -> Dimension:
    """线宽/过孔孔径/环宽 vs 工艺能力。逐项通过率。"""
    checks = 0
    fails = 0
    bad: Dict[str, int] = {}
    for s in board.segments():
        checks += 1
        if s.width < FAB_MIN_TRACE_MM - 1e-6:
            fails += 1
            bad["线宽过细"] = bad.get("线宽过细", 0) + 1
    for v in board.vias():
        checks += 1
        if v.drill < FAB_MIN_VIA_DRILL - 1e-6:
            fails += 1
            bad["过孔孔径过小"] = bad.get("过孔孔径过小", 0) + 1
        checks += 1
        annular = (v.size - v.drill) / 2.0
        if annular < FAB_MIN_VIA_ANNULAR - 1e-6:
            fails += 1
            bad["过孔环宽不足"] = bad.get("过孔环宽不足", 0) + 1
    for fp in board.footprints():
        for pad in fp.pads():
            d = pad.drill
            if d <= 0:
                continue
            checks += 1
            annular = (min(pad.width, pad.height) - d) / 2.0
            if annular < FAB_MIN_PAD_ANNULAR - 1e-6:
                fails += 1
                bad["焊盘环宽不足"] = bad.get("焊盘环宽不足", 0) + 1
    if checks == 0:
        return Dimension("dfm", "可制造性", 100.0, WEIGHTS["dfm"], "无可检项")
    score = 100.0 * (checks - fails) / checks
    issues = [f"{k} × {c}" for k, c in sorted(bad.items(), key=lambda t: -t[1])]
    return Dimension("dfm", "可制造性", score, WEIGHTS["dfm"],
                     f"{checks-fails}/{checks} 项符合 JLCPCB 工艺", issues)


def _dim_power(board: Board, rep: DRCReport) -> Dimension:
    """接地铺铜覆盖率 + 去耦电容 + 电源/地网连通。"""
    names = {n.number: n.name for n in board.nets()}
    zarea = _zone_area_by_net(board)
    barea = _board_area(board)
    gnd_area = sum(a for n, a in zarea.items() if _is_ground(names.get(n, "")))
    coverage = min(1.0, gnd_area / barea)
    cov_score = 100.0 * min(1.0, coverage / GND_TARGET_COVERAGE)

    # 去耦电容: 电容数 / IC 数 (经验 ≥1)
    n_cap = sum(1 for fp in board.footprints() if fp.ref.upper().startswith("C"))
    n_ic = sum(1 for fp in board.footprints() if fp.ref.upper().startswith("U"))
    if n_ic == 0:
        dec_score = 100.0
        dec_detail = "无 IC"
    else:
        ratio = n_cap / n_ic
        dec_score = 100.0 * min(1.0, ratio)   # 每 IC 至少 1 个去耦电容
        dec_detail = f"{n_cap} 电容 / {n_ic} IC"

    # 电源/地网是否连通 (开路里有没有电源地网)
    open_nets = {v.extra.get("net_number") for v in rep.violations
                 if v.rule == "R008" and v.severity == "error"}
    pg_open = [names.get(n, f"#{n}") for n in open_nets
               if _is_ground(names.get(n, "")) or _is_power(names.get(n, ""))]

    score = 0.5 * cov_score + 0.3 * dec_score + 0.2 * (0.0 if pg_open else 100.0)
    issues = []
    if coverage < GND_TARGET_COVERAGE:
        issues.append(f"GND 铺铜覆盖率仅 {coverage*100:.0f}% "
                      f"(建议 ≥{GND_TARGET_COVERAGE*100:.0f}%)")
    if n_ic and n_cap < n_ic:
        issues.append(f"去耦电容偏少 ({dec_detail}, 建议每 IC ≥1)")
    if pg_open:
        issues.append(f"电源/地网未连通: {', '.join(pg_open[:6])}")
    return Dimension("power", "电源地完整", score, WEIGHTS["power"],
                     f"GND 覆盖 {coverage*100:.0f}% · {dec_detail}", issues)


def _dim_placement(board: Board, rep: DRCReport) -> Dimension:
    """元件不出板/不重号 + 板面利用率合理。"""
    off = [v for v in rep.violations if v.rule == "R002"]
    dup = [v for v in rep.violations if v.rule == "R003"]
    # 利用率 = 元件本体并集面积 / 板面积 (粗略: 焊盘包络)
    barea = _board_area(board)
    comp_area = 0.0
    for fp in board.footprints():
        bb = fp.bbox
        if not bb.empty:
            comp_area += bb.width * bb.height
    util = comp_area / barea if barea > 0 else 0.0

    score = 100.0
    issues = []
    if dup:
        score -= 40.0 * min(2, len(dup))
        issues.append(f"{len(dup)} 处元件重号 (致命)")
    if off:
        score -= 10.0 * min(4, len(off))
        issues.append(f"{len(off)} 个元件超出板边")
    # 利用率: 8%~55% 合理; 过低=空旷(摆放差), 过高=拥挤
    if util < 0.08:
        score -= 15.0
        issues.append(f"板面利用率仅 {util*100:.0f}% (元件过于空旷, 易致绕线远)")
    elif util > 0.60:
        score -= 10.0
        issues.append(f"板面利用率 {util*100:.0f}% (过于拥挤, 逃逸困难)")
    score = max(0.0, score)
    return Dimension("placement", "布局与规则", score, WEIGHTS["placement"],
                     f"利用率 {util*100:.0f}% · 出板 {len(off)} · 重号 {len(dup)}",
                     issues)


# ─────────────────────────────────────────────────────────────────────
# 顶层
# ─────────────────────────────────────────────────────────────────────
def score_board(board: Board, name: str,
                rep: Optional[DRCReport] = None) -> QualityScore:
    """对一块板做客观质量评分。rep 缺省自动跑诚实 DRC。"""
    if rep is None:
        rep = run_drc(board)
    dims = [
        _dim_connectivity(board, rep),
        _dim_shorts(board, rep),
        _dim_clearance(board, rep),
        _dim_dfm(board),
        _dim_power(board, rep),
        _dim_placement(board, rep),
    ]
    wsum = sum(d.weight for d in dims) or 1.0
    raw = sum(d.score * d.weight for d in dims) / wsum

    n_short = sum(1 for v in rep.violations
                  if v.rule in ("R001", "R005", "R007") and v.severity == "error")
    n_open = sum(1 for v in rep.violations
                 if v.rule == "R008" and v.severity == "error")
    manufacturable = (n_short == 0 and n_open == 0)

    # ── 诚实封顶: 不可制造的板永远进不了"及格区" (反者道之动, 不许虚高) ──
    # 能造的板按加权分; 不能造的板按"离可制造多远"压进 0-59 的 F 区。
    conn = next(d for d in dims if d.key == "connectivity")
    if manufacturable:
        overall = raw
        grade = _grade(overall)
    elif n_short:
        # 硬短路最致命 (会烧板) → 深 F 区
        overall = max(0.0, min(35.0, raw * 0.35))
        grade = "F"
    else:
        # 仅开路 (功能不全): 用布线完成度映射到 0-58, 越接近全连通越高
        overall = min(58.0, 0.58 * conn.score)
        grade = "F"

    # 客观结论
    if manufacturable and overall >= 90:
        headline = "可直接投产: 无短路无开路, 各维度优良。"
    elif manufacturable:
        headline = "可制造: 无短路无开路; 仍有非致命项可优化 (见下)。"
    elif n_short:
        headline = f"不可制造: {n_short} 处硬短路 (会烧板), 必须先消短路。"
    else:
        headline = f"不可制造: {n_open} 条网络开路 (功能不全), 必须先布通。"

    # 缺陷清单 (按维度权重 × 失分排序, 高杠杆在前)
    ranked: List[Tuple[float, str]] = []
    for d in dims:
        lever = d.weight * (100.0 - d.score) / 100.0
        for it in d.issues:
            ranked.append((lever, f"[{d.label}] {it}"))
    ranked.sort(key=lambda t: -t[0])
    fix_list = [t[1] for t in ranked]

    return QualityScore(
        board_name=name, overall=overall, grade=grade,
        manufacturable=manufacturable, dimensions=dims,
        headline=headline, fix_list=fix_list,
    )


# ─────────────────────────────────────────────────────────────────────
# 自检 / CLI
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        b = Board.load(sys.argv[1])
        nm = sys.argv[2] if len(sys.argv) > 2 else "board"
        qs = score_board(b, nm)
        print(json.dumps(qs.to_dict(), ensure_ascii=False, indent=2))
    else:
        b = Board.empty(width_mm=50, height_mm=40)
        qs = score_board(b, "empty")
        print(json.dumps(qs.to_dict(), ensure_ascii=False, indent=2))
