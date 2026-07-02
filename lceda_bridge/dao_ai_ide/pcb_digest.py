#!/usr/bin/env python3
"""pcb_digest — 云端/本地 Agent 一次性感知整个 PCB 工程全貌(像看一个文件).

用法:
    python3 pcb_digest.py            # markdown 全貌报告 → stdout
    python3 pcb_digest.py --json    # 原始 JSON
    DAO_CDP_PORT=29230 可覆盖 CDP 端口(默认 29230)

依赖: ../cdp_studio/dao_eda_cdp_driver.py (同仓库), EDA 桌面端已带 --remote-debugging-port 启动.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cdp_studio"))
import dao_eda_cdp_driver as drv  # noqa: E402

DIGEST_JS = r"""
(async function () {
  var R = window.top._EXTAPI_ROOT_ || window._EXTAPI_ROOT_;
  async function g(ns, m, a) {
    try { return await R[ns][m].apply(R[ns], a || []); } catch (e) { return null; }
  }
  var dg = { generatedAt: new Date().toISOString() };
  dg.version = await g('sys_Environment', 'getEditorCurrentVersion');
  dg.project = await g('dmt_Project', 'getCurrentProjectInfo');
  dg.pcb = await g('dmt_Pcb', 'getCurrentPcbInfo');
  dg.copperLayers = await g('pcb_Layer', 'getTheNumberOfCopperLayers');
  dg.nets = await g('pcb_Net', 'getAllNetsName') || await g('pcb_Net', 'getAllNetName');
  var types = ['Component','Via','Line','Arc','Pad','Fill','Pour','String','Region','Polyline'];
  dg.primitives = {};
  for (var i = 0; i < types.length; i++) {
    var all = await g('pcb_Primitive' + types[i], 'getAll');
    if (!all) continue;
    var entry = { count: all.length };
    if (types[i] === 'Component') entry.items = all.map(function (c) {
      return { designator: c.designator || c.name, x: c.x, y: c.y, layer: c.layer,
               footprint: c.footprintName || c.device || undefined };
    });
    else if (DETAIL === 'full') entry.items = all;
    dg.primitives[types[i]] = entry;
  }
  dg.drcRealtime = await g('pcb_Drc', 'getRealTimeDrcStatus');
  var bl = await g('pcb_Primitive', 'getPrimitiveBoardLine');
  if (bl) dg.boardOutline = bl;
  return JSON.stringify(dg);
})()
"""


def fetch_digest(port=None, detail="summary"):
    port = port or int(os.environ.get("DAO_CDP_PORT", "29230"))
    ws = drv.connect_editor(port)
    js = "var DETAIL=%s;%s" % (json.dumps(detail), DIGEST_JS)
    out, err = drv.evaluate(ws, js, await_promise=True, timeout=60)
    if err:
        raise RuntimeError("digest evaluate failed: %s" % err)
    return json.loads(out)


def render_markdown(dg):
    lines = ["# PCB 工程全貌 (project digest)", ""]
    lines.append("- 生成时间: %s · EDA v%s" % (dg.get("generatedAt"), dg.get("version")))
    p, b = dg.get("project") or {}, dg.get("pcb") or {}
    lines.append("- 工程: %s (uuid=%s)" % (p.get("name") or p.get("friendlyName"), p.get("uuid")))
    lines.append("- 板: %s (uuid=%s) · 铜层数: %s" % (b.get("name"), b.get("uuid"), dg.get("copperLayers")))
    nets = dg.get("nets") or []
    lines.append("- 网络 %d 个: %s" % (len(nets), ", ".join(map(str, nets[:40])) or "(无)"))
    lines.append("")
    lines.append("## 图元统计")
    lines.append("| 类型 | 数量 |")
    lines.append("|---|---|")
    prim = dg.get("primitives") or {}
    for t, e in prim.items():
        lines.append("| %s | %s |" % (t, e.get("count")))
    comp = (prim.get("Component") or {}).get("items") or []
    if comp:
        lines.append("")
        lines.append("## 器件清单")
        lines.append("| 位号 | X | Y | 层 | 封装 |")
        lines.append("|---|---|---|---|---|")
        for c in comp:
            lines.append("| %s | %s | %s | %s | %s |" % (
                c.get("designator"), c.get("x"), c.get("y"), c.get("layer"), c.get("footprint")))
    lines.append("")
    lines.append("- 实时DRC状态: %s" % dg.get("drcRealtime"))
    if dg.get("boardOutline") is not None:
        lines.append("- 板框: %s" % json.dumps(dg["boardOutline"], ensure_ascii=False)[:400])
    return "\n".join(lines)


if __name__ == "__main__":
    detail = "full" if "--full" in sys.argv else "summary"
    dg = fetch_digest(detail=detail)
    if "--json" in sys.argv:
        print(json.dumps(dg, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(dg))
