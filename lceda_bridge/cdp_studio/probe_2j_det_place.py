#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话 2j 实证:确定性放件 —— 经逆出的 `sch_PrimitiveComponent.create` 真实签名,
按**数据坐标**直接落件,不依赖视口/合成鼠标,放点逐一精确可复验。

逆出签名(读 live fa 构造源 + create rpc 入参):
  create(device, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
  · device = {uuid, libraryUuid, name}
  · x,y 为图纸数据坐标(worker 内 y、rotation 取负);subPartName="" 即可
  · 多脚/同器件可任意次放置,各自独立落库(无合成鼠标去重问题)

验证:对同一电阻 device 连放 N 个到精确数据坐标 → 读回每个 getState_X/Y == 期望。
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d  # noqa: E402
import eda_flow  # noqa: E402


def jstr(x):
    return json.dumps(x, ensure_ascii=False)


def create_part(ws, device, x, y, sub="", rot=0, mirror=False, bom=True, pcb=True):
    js = (r"(async function(){try{var pc=window._EXTAPI_ROOT_.sch_PrimitiveComponent;"
          r"var r=await pc.create(%s,%d,%d,%s,%d,%s,%s,%s);"
          r"return JSON.stringify({id:(r&&r.getState_PrimitiveId)?r.getState_PrimitiveId():null,"
          r"x:r&&r.getState_X(),y:r&&r.getState_Y(),rot:r&&r.getState_Rotation(),des:r&&r.getState_Designator()});}"
          r"catch(err){return JSON.stringify({err:String(err)});}})()"
          % (jstr(device), x, y, jstr(sub), rot,
             "true" if mirror else "false", "true" if bom else "false", "true" if pcb else "false"))
    v, e = d.evaluate(ws, js, await_promise=True, timeout=20)
    return json.loads(v) if v else {"evalerr": e}


def main():
    f = eda_flow.Flow()
    h = f.scaffold("DAO-2j-det")
    print("[scaffold]", jstr(h))
    f.open_document(h["page"], "sch", tries=8, gap=2)
    time.sleep(2)

    res = f.search_device("0603 10k")
    lst = res if isinstance(res, list) else (res.get("result") or [])
    dev = lst[0]
    device = {"uuid": dev["uuid"], "libraryUuid": dev["libraryUuid"], "name": dev.get("name")}
    print("[device]", jstr(device))

    before = set(f.parts())
    # 同一 device 连放 5 个到精确数据坐标(刻意测"相同器件不被去重")
    targets = [(0, 0), (200, 0), (400, 0), (0, 200), (200, 200)]
    placed = []
    for (x, y) in targets:
        r = create_part(f.ws, device, x, y)
        print("[create]", (x, y), "->", jstr(r))
        placed.append((x, y, r))
        time.sleep(0.5)

    time.sleep(2)
    f.save_sch()
    time.sleep(2)
    after = set(f.parts())
    new = after - before
    print("[parts before]", len(before), "[after]", len(after), "[new]", len(new))

    # 逐一读回,核对 (期望 x,y) == (落库 x,y)。注意 create 内对 y 取负→读回应等于传入。
    ok = 0
    for x, y, r in placed:
        pid = r.get("id")
        if not pid:
            print("  [MISS]", (x, y), r); continue
        match = (r.get("x") == x and r.get("y") == y)
        ok += 1 if match else 0
        print("  [verify]", (x, y), "landed", (r.get("x"), r.get("y")), "EXACT" if match else "MISMATCH", "des", r.get("des"))
    print("[deterministic result] %d/%d landed exactly at requested data coords" % (ok, len(placed)))


if __name__ == "__main__":
    main()
