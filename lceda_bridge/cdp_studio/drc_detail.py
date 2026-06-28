#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drc_detail — 导航到刚建好的密板,探测 pcb_Drc API 并拉出**逐条 DRC 违规明细**。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d
import eda_flow

PROJECT = "b4404a49ffc14d388957881183b4671b"
PCB = "10af0bf5594ebe5f"


def main():
    f = eda_flow.Flow()
    f.open_project(PROJECT)
    f.open_document(PCB)
    time.sleep(2)
    f.reload_and_reopen(PROJECT, PCB)
    time.sleep(2)

    R = "window._EXTAPI_ROOT_"
    js = ("(()=>{try{var o=%s.pcb_Drc;"
          "return JSON.stringify(Object.getOwnPropertyNames(Object.getPrototypeOf(o)).concat(Object.keys(o)));"
          "}catch(e){return 'ERR '+e}})()" % R)
    v, e = d.evaluate(f.ws, js, await_promise=False, timeout=15)
    print("Drc methods:", v)

    # 运行 check 并尝试各种取明细的方法
    for meth in ("check", "getResult", "getResults", "getDrcResult", "getErrorList",
                 "getDrcErrorList", "getAllDrcError", "getViolations"):
        js2 = ("(async()=>{try{var r=await %s.pcb_Drc.%s();"
               "return JSON.stringify(r).slice(0,1500);}catch(e){return 'ERR '+String(e.message||e).slice(0,80)}})()"
               % (R, meth))
        v2, e2 = d.evaluate(f.ws, js2, await_promise=True, timeout=70)
        print("==", meth, "->", (v2 or e2))


if __name__ == "__main__":
    main()
