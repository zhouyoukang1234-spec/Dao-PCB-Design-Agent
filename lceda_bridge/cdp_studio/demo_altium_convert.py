# -*- coding: utf-8 -*-
"""demo_altium_convert — Altium 库 → EasyEDA 转换实战(Altium 生态 → JLC,零 GUI)。

逆出并实测 `sys_FormatConversion.convertAltiumDesignerLibrariesToEasyEDASingleFile(File)`:
把真实 Altium 库文件(OLE 复合二进制 .SchLib/.PcbLib)在页内重建为 File 喂入,
确认 JLC 返回转换后的 EasyEDA 结构 → 业界 Altium 资产可流入本系统库。
"""
import base64
import json
import os
import sys

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d
import eda_flow


def convert_altium(f, lib_path, multi=False, timeout=120):
    """把 Altium .SchLib/.PcbLib 喂入转换端点,返回结果摘要(类型/键/长度)。"""
    raw = open(lib_path, "rb").read()
    b64 = base64.b64encode(raw).decode()
    method = ("convertAltiumDesignerLibrariesToEasyEDAMultiFiles" if multi
              else "convertAltiumDesignerLibrariesToEasyEDASingleFile")
    fname = os.path.basename(lib_path)
    js = (
        "(async()=>{try{"
        "var bin=atob(%s);var a=new Uint8Array(bin.length);"
        "for(var i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);"
        "var file=new File([a],%s);"
        "var r=await window._EXTAPI_ROOT_.sys_FormatConversion.%s(file);"
        "var summary={ok:true,type:Object.prototype.toString.call(r)};"
        "try{if(r&&r.constructor&&r.constructor.name)summary.ctor=r.constructor.name;}catch(_){}"
        "try{if(typeof r==='string'){summary.len=r.length;summary.head=r.slice(0,200);}"
        "else if(r&&r.arrayBuffer){var b=new Uint8Array(await r.arrayBuffer());summary.fileName=r.name;summary.bytes=b.length;}"
        "else if(Array.isArray(r)){summary.arrLen=r.length;summary.sample=JSON.stringify(r[0]).slice(0,200);}"
        "else if(r&&typeof r==='object'){summary.keys=Object.keys(r).slice(0,25);summary.json=JSON.stringify(r).slice(0,300);}}catch(_){}"
        "return JSON.stringify(summary);"
        "}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
        % (json.dumps(b64), json.dumps(fname), method)
    )
    v, e = d.evaluate(f.ws, js, await_promise=True, timeout=timeout)
    if e:
        return {"ok": False, "transport_err": e}
    return json.loads(v)


def run():
    f = eda_flow.Flow()
    out = {}
    for tag, path, multi in [
        ("SchLib_single", "C:/tools/AP7375.SchLib", False),
        ("PcbLib_single", "C:/tools/PCB_SDCard.PcbLib", False),
        ("SchLib_multi", "C:/tools/AP7375.SchLib", True),
    ]:
        if not os.path.exists(path):
            out[tag] = {"ok": False, "err": "missing %s" % path}
            continue
        out[tag] = {"src_bytes": os.path.getsize(path)}
        out[tag].update(convert_altium(f, path, multi=multi))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
