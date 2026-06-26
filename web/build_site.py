#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site — 把全部已生成的 PCB 渲染成静态可视化网页 (公网可托管, 纯静态)。

对每块板:
  * 解析 .kicad_pcb (kicad_origin.Board)
  * 渲染 SVG: Edge.Cuts 板框 / F.Cu 走线(红) / B.Cu 走线(蓝) / 焊盘(金) / 过孔(绿)
  * 跑诚实 DRC (R001-R008) 收集 error/warning, 并把违规点标在板上
  * 读 pipeline_report.json 抽参数 (元件/网络/板尺寸/BOM 成本/自由能)

输出: docs/  (index.html + 每板一页 + 内联 SVG, 无外链, 可直接 GitHub Pages 托管)

道法自然: 视觉即真值 — 自由能虚高与隐性短路, 一眼可见。
"""
from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kicad_origin.pcb.board import Board          # noqa: E402
from kicad_origin.engine.drc import run_drc        # noqa: E402
from kicad_origin.engine.quality import score_board  # noqa: E402

OUTPUT_DIR = ROOT / "pcb_brain" / "output"
DOCS_DIR = ROOT / "docs"

# ── 颜色 (深色 PCB 主题) ──
COL_BG = "#0b0f14"
COL_BOARD = "#0d3b2e"
COL_EDGE = "#39ff14"
COL_FCU = "#ff4d4d"
COL_BCU = "#4d79ff"
COL_PAD = "#ffcc33"
COL_PAD_NC = "#8a7a3a"
COL_VIA = "#33ffcc"
COL_ERR = "#ff2d2d"
COL_WARN = "#ffae42"
COL_TEXT = "#cfe8ff"
COL_BODY = "#1b2733"      # 元件本体填充 (深灰蓝)
COL_BODY_B = "#241b2e"    # B 面元件本体
COL_CRTYD = "#5a6b7a"     # courtyard / 丝印外框
COL_REF = "#e8f3ff"       # 位号文字
COL_ZONE_F = "#7a2e2e"    # F.Cu 铺铜 (暗红, 半透明)
COL_ZONE_B = "#2e3d7a"    # B.Cu 铺铜 (暗蓝, 半透明)


def _rotate(lx: float, ly: float, deg: float) -> tuple[float, float]:
    """KiCad 焊盘世界坐标旋转 (y 向下; 正角顺时针视觉)。"""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return lx * c - ly * s, lx * s + ly * c


def _pad_abs(fp, pad):
    fx, fy = fp.position.x, fp.position.y
    lx, ly = pad.position.x, pad.position.y
    rx, ry = _rotate(lx, ly, fp.rotation)
    return fx + rx, fy + ry


def _fp_body_bbox(fp):
    """元件本体外接矩形 (世界坐标, 含旋转): 焊盘外包络再外扩一圈作 courtyard。
    返回 (x0,y0,x1,y1) 或 None。"""
    xs, ys = [], []
    for pad in fp.pads():
        ax, ay = _pad_abs(fp, pad)
        hw = max(0.1, pad.width / 2.0)
        hh = max(0.1, pad.height / 2.0)
        xs += [ax - hw, ax + hw]
        ys += [ay - hh, ay + hh]
    if not xs:
        return None
    margin = 0.35  # courtyard 余量 (mm)
    return (min(xs) - margin, min(ys) - margin,
            max(xs) + margin, max(ys) + margin)


def _layer_color(layer: str) -> str:
    if layer == "B.Cu":
        return COL_BCU
    return COL_FCU


def render_svg(board: Board, violations, width_px: int = 900) -> tuple[str, dict]:
    """返回 (svg_str, geom_stats)。"""
    # ── 计算绘图范围 ──
    xs, ys = [], []
    bo = board.board_outline()
    if bo and not bo.empty:
        xs += [bo.x_min, bo.x_max]
        ys += [bo.y_min, bo.y_max]
    for fp in board.footprints():
        for pad in fp.pads():
            ax, ay = _pad_abs(fp, pad)
            xs.append(ax)
            ys.append(ay)
    for seg in board.segments():
        xs += [seg.start.x, seg.end.x]
        ys += [seg.start.y, seg.end.y]
    for via in board.vias():
        xs.append(via.position.x)
        ys.append(via.position.y)
    if not xs:
        xs, ys = [0, 100], [0, 80]

    pad_mm = 4.0
    x_min, x_max = min(xs) - pad_mm, max(xs) + pad_mm
    y_min, y_max = min(ys) - pad_mm, max(ys) + pad_mm
    w_mm = max(1.0, x_max - x_min)
    h_mm = max(1.0, y_max - y_min)
    scale = width_px / w_mm
    height_px = h_mm * scale

    def X(x):
        return (x - x_min) * scale

    def Y(y):
        return (y - y_min) * scale

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px:.0f} '
        f'{height_px:.0f}" width="100%" style="background:{COL_BG};'
        f'border-radius:8px">')

    # ── 板框 ──
    if bo and not bo.empty:
        out.append(
            f'<rect x="{X(bo.x_min):.1f}" y="{Y(bo.y_min):.1f}" '
            f'width="{(bo.width*scale):.1f}" height="{(bo.height*scale):.1f}" '
            f'fill="{COL_BOARD}" stroke="{COL_EDGE}" stroke-width="2" '
            f'rx="4" opacity="0.85"/>')

    # ── 铺铜 zone (走线之下、板框之上) ──
    for z in board.zones():
        zlayer = z.layer or "F.Cu"
        zcol = COL_ZONE_B if "B.Cu" in zlayer else COL_ZONE_F
        # 优先画已填充多边形, 否则退回用户定义边界
        polys = z.filled_polygon_points() or ([z.polygon_points()]
                                              if z.polygon_points() else [])
        for poly in polys:
            if len(poly) < 3:
                continue
            pts = " ".join(f"{X(p.x):.1f},{Y(p.y):.1f}" for p in poly)
            out.append(
                f'<polygon points="{pts}" fill="{zcol}" '
                f'stroke="none" opacity="0.38"/>')

    # ── 元件本体 + 丝印位号 (走线之下, 焊盘之下: 先铺底) ──
    n_fp_drawn = 0
    for fp in board.footprints():
        bb = _fp_body_bbox(fp)
        if bb is None:
            continue
        bx0, by0, bx1, by1 = bb
        is_back = fp.is_back_side
        body_col = COL_BODY_B if is_back else COL_BODY
        out.append(
            f'<rect x="{X(bx0):.1f}" y="{Y(by0):.1f}" '
            f'width="{((bx1-bx0)*scale):.1f}" height="{((by1-by0)*scale):.1f}" '
            f'rx="2" fill="{body_col}" stroke="{COL_CRTYD}" '
            f'stroke-width="1" opacity="0.92"/>')
        n_fp_drawn += 1
        # 位号 (元件中心)
        cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
        fsz = max(7.0, min(13.0, ((bx1 - bx0) * scale) * 0.30))
        out.append(
            f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" fill="{COL_REF}" '
            f'font-size="{fsz:.1f}" font-family="monospace" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'opacity="0.85">{_esc(fp.ref)}</text>')

    # ── 走线 (B.Cu 先画, F.Cu 后画) ──
    segs = board.segments()
    for layer_filter in ("B.Cu", "F.Cu"):
        for seg in segs:
            if seg.layer != layer_filter:
                continue
            col = _layer_color(seg.layer)
            wpx = max(1.0, seg.width * scale)
            out.append(
                f'<line x1="{X(seg.start.x):.1f}" y1="{Y(seg.start.y):.1f}" '
                f'x2="{X(seg.end.x):.1f}" y2="{Y(seg.end.y):.1f}" '
                f'stroke="{col}" stroke-width="{wpx:.1f}" '
                f'stroke-linecap="round" opacity="0.85"/>')

    # ── 焊盘 ──
    n_pads = 0
    for fp in board.footprints():
        for pad in fp.pads():
            ax, ay = _pad_abs(fp, pad)
            n_pads += 1
            hw = max(0.2, pad.width / 2.0) * scale
            hh = max(0.2, pad.height / 2.0) * scale
            col = COL_PAD if pad.net_number > 0 else COL_PAD_NC
            rx = 2 if pad.shape in ("roundrect", "circle", "oval") else 0
            out.append(
                f'<rect x="{X(ax)-hw:.1f}" y="{Y(ay)-hh:.1f}" '
                f'width="{2*hw:.1f}" height="{2*hh:.1f}" rx="{rx}" '
                f'fill="{col}" opacity="0.9"/>')

    # ── 过孔 ──
    for via in board.vias():
        rpx = max(1.5, via.size / 2.0 * scale)
        out.append(
            f'<circle cx="{X(via.position.x):.1f}" cy="{Y(via.position.y):.1f}" '
            f'r="{rpx:.1f}" fill="{COL_VIA}" stroke="#063" stroke-width="0.8"/>')

    # ── DRC 违规标记 ──
    for v in violations:
        if not v.location:
            continue
        lx, ly = v.location
        col = COL_ERR if v.severity == "error" else COL_WARN
        r = 6 if v.severity == "error" else 4
        out.append(
            f'<circle cx="{X(lx):.1f}" cy="{Y(ly):.1f}" r="{r}" '
            f'fill="none" stroke="{col}" stroke-width="2" opacity="0.9"/>')

    out.append('</svg>')
    stats = {"pads": n_pads, "segments": len(segs),
             "vias": len(board.vias()),
             "footprints": len(board.footprints()),
             "nets": len(board.nets())}
    return "\n".join(out), stats


def _esc(s) -> str:
    return html.escape(str(s))


def collect_board(out_dir: Path) -> dict | None:
    name = out_dir.name
    pcb = out_dir / f"{name}.kicad_pcb"
    if not pcb.exists():
        return None
    board = Board.load(pcb)
    report = run_drc(board)
    svg, stats = render_svg(board, report.violations)
    quality = score_board(board, name, report).to_dict()

    rep_path = out_dir / "pipeline_report.json"
    params = {}
    if rep_path.exists():
        try:
            params = json.loads(rep_path.read_text(encoding="utf-8"))
        except Exception:
            params = {}

    # 按规则聚合违规
    by_rule: dict[str, dict] = {}
    for v in report.violations:
        d = by_rule.setdefault(v.rule, {"error": 0, "warning": 0, "info": 0,
                                        "sample": v.message})
        d[v.severity] = d.get(v.severity, 0) + 1

    return {
        "name": name,
        "svg": svg,
        "stats": stats,
        "errors": report.error_count,
        "warnings": report.warning_count,
        "by_rule": by_rule,
        "params": params,
        "quality": quality,
    }


# ── HTML 模板 ──
PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#070a0e;color:#cfe8ff;
  font-family:'Segoe UI',system-ui,sans-serif;line-height:1.5}
a{color:#39ff14;text-decoration:none}
a:hover{text-decoration:underline}
header{padding:24px 32px;border-bottom:1px solid #16324a;
  background:linear-gradient(90deg,#0b0f14,#0d2233)}
h1{margin:0;font-size:24px}
.sub{color:#7fa8c9;font-size:14px;margin-top:6px}
.wrap{max-width:1200px;margin:0 auto;padding:24px 32px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:20px}
.card{background:#0d1620;border:1px solid #16324a;border-radius:10px;
  overflow:hidden;transition:.15s;display:block}
.card:hover{border-color:#39ff14;transform:translateY(-2px)}
.card .thumb{padding:8px;background:#0b0f14}
.card .meta{padding:12px 14px}
.card .meta h3{margin:0 0 6px;font-size:16px;color:#fff}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;
  font-weight:600;margin-right:6px}
.b-ok{background:#0d3b2e;color:#39ff14}
.b-err{background:#3b0d12;color:#ff6b6b}
.b-warn{background:#3b2f0d;color:#ffcc33}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
th,td{border:1px solid #16324a;padding:6px 10px;text-align:left}
th{background:#0d2233;color:#7fa8c9}
.legend span{display:inline-block;margin-right:16px;font-size:13px}
.dot{display:inline-block;width:12px;height:12px;border-radius:3px;
  margin-right:5px;vertical-align:middle}
.summary{display:flex;gap:24px;flex-wrap:wrap;margin-top:12px}
.stat{background:#0d1620;border:1px solid #16324a;border-radius:8px;
  padding:12px 18px;min-width:120px}
.stat .n{font-size:26px;font-weight:700;color:#fff}
.stat .l{font-size:12px;color:#7fa8c9}
.back{margin-bottom:16px;display:inline-block}
/* ── 质量评分卡 ── */
.grade{display:inline-flex;align-items:center;justify-content:center;
  width:34px;height:34px;border-radius:8px;font-weight:800;font-size:18px;
  color:#06121a}
.gA{background:#39ff14}.gB{background:#5be3c0}.gC{background:#ffd24d}
.gD{background:#ff9b3d}.gF{background:#ff5b5b}
.score-big{font-size:40px;font-weight:800;color:#fff;line-height:1}
.score-of{font-size:15px;color:#7fa8c9}
.headline{font-size:15px;margin:10px 0 4px;padding:10px 14px;border-radius:8px;
  background:#0d1620;border-left:4px solid #39ff14}
.headline.bad{border-left-color:#ff5b5b}
.mfg{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;
  font-weight:700}
.mfg-ok{background:#0d3b2e;color:#39ff14}
.mfg-ng{background:#3b0d12;color:#ff6b6b}
.dim{margin:8px 0}
.dim .top{display:flex;justify-content:space-between;font-size:13px}
.dim .lab{color:#cfe8ff}.dim .val{color:#7fa8c9}
.bar{height:9px;border-radius:5px;background:#16242f;overflow:hidden;margin-top:3px}
.bar>i{display:block;height:100%;border-radius:5px}
.dim .det{font-size:12px;color:#6f93b0;margin-top:2px}
.fixes{margin:10px 0 0;padding-left:0;list-style:none}
.fixes li{background:#1c1407;border-left:3px solid #ffcc33;padding:6px 10px;
  margin:5px 0;border-radius:4px;font-size:13px;color:#ffe2a6}
.scorecard{background:#0d1620;border:1px solid #16324a;border-radius:10px;
  padding:16px 18px;margin:14px 0}
.schead{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.mini-grade{font-size:12px;color:#7fa8c9;margin-top:4px}
"""


def _bar_color(score: float) -> str:
    if score >= 90:
        return "#39ff14"
    if score >= 75:
        return "#5be3c0"
    if score >= 60:
        return "#ffd24d"
    if score >= 40:
        return "#ff9b3d"
    return "#ff5b5b"


def render_dimensions(q: dict) -> str:
    out = []
    for d in q["dimensions"]:
        sc = d["score"]
        col = _bar_color(sc)
        det = f'<div class="det">{_esc(d["detail"])}</div>' if d["detail"] else ""
        out.append(
            f'<div class="dim"><div class="top">'
            f'<span class="lab">{_esc(d["label"])} '
            f'<span style="color:#56708a">(权重{d["weight"]})</span></span>'
            f'<span class="val">{sc:.0f}/100</span></div>'
            f'<div class="bar"><i style="width:{max(2,sc):.0f}%;'
            f'background:{col}"></i></div>{det}</div>')
    return "".join(out)


def render_fixes(q: dict) -> str:
    if not q["fix_list"]:
        return '<p style="color:#39ff14">✓ 无遗留缺陷项。</p>'
    items = "".join(f"<li>{_esc(x)}</li>" for x in q["fix_list"])
    return f'<ul class="fixes">{items}</ul>'


def board_status_badges(b) -> str:
    if b["errors"] == 0 and b["warnings"] == 0:
        return '<span class="badge b-ok">零缺陷</span>'
    out = ""
    if b["errors"]:
        out += f'<span class="badge b-err">{b["errors"]} 错误</span>'
    if b["warnings"]:
        out += f'<span class="badge b-warn">{b["warnings"]} 警告</span>'
    return out


def _qkey(b: dict):
    """排序键: 质量分降序 (评分卡是客观真值排名依据)。"""
    return (-b["quality"]["overall"], b["name"])


def build_index(boards: list[dict]) -> str:
    total_err = sum(b["errors"] for b in boards)
    total_warn = sum(b["warnings"] for b in boards)
    mfg = sum(1 for b in boards if b["quality"]["manufacturable"])
    avg = (sum(b["quality"]["overall"] for b in boards) / len(boards)
           if boards else 0.0)
    ordered = sorted(boards, key=_qkey)

    # 排行榜 (客观分高→低)
    rank_rows = []
    for i, b in enumerate(ordered, 1):
        q = b["quality"]
        g = q["grade"]
        mtag = ('<span class="mfg mfg-ok">可制造</span>'
                if q["manufacturable"]
                else '<span class="mfg mfg-ng">不可制造</span>')
        rank_rows.append(
            f"<tr><td>{i}</td>"
            f"<td><a href='board_{_esc(b['name'])}.html'>{_esc(b['name'])}</a></td>"
            f"<td><span class='grade g{g}'>{g}</span></td>"
            f"<td><b style='color:#fff'>{q['overall']:.1f}</b></td>"
            f"<td>{mtag}</td>"
            f"<td style='color:#9fb8cf;font-size:13px'>{_esc(q['headline'])}</td></tr>")
    rank_table = (
        "<table><tr><th>#</th><th>板</th><th>等级</th><th>客观分</th>"
        "<th>可制造性</th><th>客观结论</th></tr>"
        + "".join(rank_rows) + "</table>")

    cards = []
    for b in ordered:
        q = b["quality"]
        g = q["grade"]
        cards.append(f"""
      <a class="card" href="board_{_esc(b['name'])}.html">
        <div class="thumb">{b['svg']}</div>
        <div class="meta">
          <h3><span class="grade g{g}" style="width:26px;height:26px;
            font-size:14px;vertical-align:middle;margin-right:8px">{g}</span>
            {_esc(b['name'])}
            <span style="float:right;color:#fff;font-weight:700">{q['overall']:.0f}</span></h3>
          {board_status_badges(b)}
          <div class="sub">{b['stats']['footprints']} 元件 ·
            {b['stats']['nets']} 网络 · {b['stats']['segments']} 走线 ·
            {b['stats']['vias']} 过孔</div>
        </div>
      </a>""")
    return f"""<!DOCTYPE html><html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport"
  content="width=device-width,initial-scale=1">
<title>Dao-PCB · 全板客观质量审视</title><style>{PAGE_CSS}</style></head><body>
<header>
  <h1>☯ Dao-PCB Design Agent · 全板客观质量审视</h1>
  <div class="sub">诚实 oracle (R001-R008 DRC) · 客观质量评分卡 (6 维度 0-100) ·
    任何水平都能看懂每块板好不好、还差什么 · 道法自然</div>
  <div class="summary">
    <div class="stat"><div class="n">{len(boards)}</div><div class="l">板数</div></div>
    <div class="stat"><div class="n" style="color:#39ff14">{mfg}</div>
      <div class="l">可制造板 (无短路无开路)</div></div>
    <div class="stat"><div class="n" style="color:#fff">{avg:.1f}</div>
      <div class="l">平均客观分</div></div>
    <div class="stat"><div class="n" style="color:#ff6b6b">{total_err}</div>
      <div class="l">诚实 DRC 错误总数</div></div>
    <div class="stat"><div class="n" style="color:#ffcc33">{total_warn}</div>
      <div class="l">警告总数</div></div>
  </div>
</header>
<div class="wrap">
  <h2>客观质量排行榜</h2>
  <p class="sub" style="margin:0 0 6px">评分维度: 连通完整性(30) · 短路安全(25) ·
    间距余量(12) · 可制造性(13) · 电源地完整(12) · 布局与规则(8)。
    凡有短路/开路即判"不可制造", 客观分封顶 F 区 — 反者道之动, 不许虚高。</p>
  {rank_table}
  <h2 style="margin-top:28px">全板视图</h2>
  <div class="legend" style="margin-bottom:14px">
    <span><i class="dot" style="background:{COL_FCU}"></i>F.Cu 走线</span>
    <span><i class="dot" style="background:{COL_BCU}"></i>B.Cu 走线</span>
    <span><i class="dot" style="background:{COL_PAD}"></i>焊盘</span>
    <span><i class="dot" style="background:{COL_VIA}"></i>过孔</span>
    <span><i class="dot" style="border:2px solid {COL_ERR};background:none"></i>DRC 错误</span>
    <span><i class="dot" style="border:2px solid {COL_WARN};background:none"></i>DRC 警告</span>
  </div>
  <div class="grid">{''.join(cards)}</div>
</div>
</body></html>"""


def _dna_components(params: dict) -> list:
    """从 pipeline stages 里抽 DNA 描述的元件 (best-effort)。"""
    return []


def build_board_page(b: dict) -> str:
    p = b["params"]
    rows = []
    rows.append(("模板", b["name"]))
    rows.append(("交付 (delivered)", p.get("delivered", "—")))
    rows.append(("自由能 (free_energy)", p.get("free_energy", "—")))
    rows.append(("BOM 成本", p.get("bom_cost", "—")))
    rows.append(("元件数", b["stats"]["footprints"]))
    rows.append(("网络数", b["stats"]["nets"]))
    rows.append(("走线段数", b["stats"]["segments"]))
    rows.append(("过孔数", b["stats"]["vias"]))
    rows.append(("焊盘数", b["stats"]["pads"]))
    info_rows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows)

    drc_rows = []
    for rule, d in sorted(b["by_rule"].items()):
        sev = "b-err" if d["error"] else "b-warn"
        drc_rows.append(
            f"<tr><td><b>{_esc(rule)}</b></td>"
            f"<td><span class='badge {sev}'>{d['error']}E / {d['warning']}W</span></td>"
            f"<td>{_esc(d['sample'])}</td></tr>")
    drc_table = ("".join(drc_rows) if drc_rows
                 else "<tr><td colspan=3>无违规 — 真正零缺陷板 ✓</td></tr>")

    q = b["quality"]
    g = q["grade"]
    mtag = ('<span class="mfg mfg-ok">✓ 可制造 (无短路无开路)</span>'
            if q["manufacturable"]
            else '<span class="mfg mfg-ng">✗ 不可制造</span>')
    hl_cls = "headline" if q["manufacturable"] else "headline bad"
    scorecard = f"""
  <div class="scorecard">
    <div class="schead">
      <span class="grade g{g}" style="width:48px;height:48px;font-size:26px">{g}</span>
      <div><span class="score-big">{q['overall']:.1f}</span>
        <span class="score-of">/ 100 客观质量分</span>
        <div class="mini-grade">{mtag}</div></div>
    </div>
    <div class="{hl_cls}">{_esc(q['headline'])}</div>
    <h3 style="margin:16px 0 4px">六维度分解</h3>
    {render_dimensions(q)}
    <h3 style="margin:16px 0 4px">还差什么 (按改进杠杆排序)</h3>
    {render_fixes(q)}
  </div>"""

    return f"""<!DOCTYPE html><html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport"
  content="width=device-width,initial-scale=1">
<title>{_esc(b['name'])} · Dao-PCB</title><style>{PAGE_CSS}</style></head><body>
<header><h1><span class="grade g{g}" style="vertical-align:middle;
  margin-right:10px">{g}</span>{_esc(b['name'])}</h1>
  <div class="sub">客观分 {q['overall']:.1f}/100 · {board_status_badges(b)}</div></header>
<div class="wrap">
  <a class="back" href="index.html">← 返回全板列表</a>
  {scorecard}
  <div class="thumb" style="background:#0b0f14;padding:12px;border-radius:8px">
    {b['svg']}
  </div>
  <div class="legend" style="margin:14px 0">
    <span><i class="dot" style="background:{COL_FCU}"></i>F.Cu</span>
    <span><i class="dot" style="background:{COL_BCU}"></i>B.Cu</span>
    <span><i class="dot" style="background:{COL_PAD}"></i>焊盘</span>
    <span><i class="dot" style="background:{COL_VIA}"></i>过孔</span>
    <span><i class="dot" style="border:2px solid {COL_ERR};background:none"></i>错误</span>
    <span><i class="dot" style="border:2px solid {COL_WARN};background:none"></i>警告</span>
  </div>
  <h2>参数</h2>
  <table>{info_rows}</table>
  <h2>诚实 DRC 违规 (按规则聚合)</h2>
  <table><tr><th>规则</th><th>计数</th><th>样例</th></tr>{drc_table}</table>
</div></body></html>"""


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    boards = []
    for out_dir in sorted(OUTPUT_DIR.iterdir()):
        if not out_dir.is_dir():
            continue
        try:
            b = collect_board(out_dir)
        except Exception as e:
            print(f"[skip] {out_dir.name}: {e}")
            continue
        if b:
            boards.append(b)
            print(f"[ok] {b['name']}: {b['errors']}E / {b['warnings']}W")

    (DOCS_DIR / "index.html").write_text(build_index(boards), encoding="utf-8")
    for b in boards:
        (DOCS_DIR / f"board_{b['name']}.html").write_text(
            build_board_page(b), encoding="utf-8")

    # 写一个机器可读汇总 (供自检/回归)
    summary = {b["name"]: {"errors": b["errors"], "warnings": b["warnings"],
                           "by_rule": b["by_rule"], "stats": b["stats"],
                           "quality": b["quality"]}
               for b in boards}
    (DOCS_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n生成 {len(boards)} 块板 → {DOCS_DIR}")
    print(f"总错误 {sum(b['errors'] for b in boards)} · "
          f"总警告 {sum(b['warnings'] for b in boards)} · "
          f"零错误板 {sum(1 for b in boards if b['errors']==0)}")


if __name__ == "__main__":
    main()
