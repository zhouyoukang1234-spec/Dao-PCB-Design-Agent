#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话 2j 取证:逆 `sch_PrimitiveComponent.create` 等放件 API 的真实签名。

经 CDP 在活体编辑器读 `_EXTAPI_ROOT_` 上各放件方法的 toString()/length,
判定确定性放件入参,替代 placeComponentWithMouse + 合成点击。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d  # noqa: E402

METHODS = [
    "sch_PrimitiveComponent.create",
    "sch_PrimitiveComponent.placeSymbolWithMouse",
    "sch_PrimitiveComponent.placeComponentWithMouse",
    "sch_PrimitiveComponent.modify",
    "sch_PrimitiveComponent.initUuid",
    "sch_PrimitiveComponent.getComponentDetail",
    "sch_PrimitiveWire.create",
    "sch_PrimitiveComponent.createNetFlag",
    "sch_PrimitiveComponent.createNetPort",
]


def main():
    ws = d._editor_session()
    out = {}
    for m in METHODS:
        js = (r"(function(){try{var f=window._EXTAPI_ROOT_;"
              r"var parts=%s.split('.');for(var i=0;i<parts.length;i++){f=f[parts[i]];}"
              r"return JSON.stringify({len:f.length,src:String(f).slice(0,900)});}"
              r"catch(e){return JSON.stringify({err:String(e)});}})()" % json.dumps(m))
        v, e = d.evaluate(ws, js, await_promise=False, timeout=10)
        try:
            out[m] = json.loads(v) if v else {"raw": v, "evalerr": e}
        except Exception:
            out[m] = {"raw": v, "evalerr": e}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
