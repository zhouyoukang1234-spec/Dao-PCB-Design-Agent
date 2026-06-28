#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resource_registry — 嘉立创EDA「天下资源」底层接入编目 + 薄封装。

道法自然·取之尽锱铢:把 PCB 全链路上可被程序化拿来即用的资源/能力,逐一逆出其
底层端点并**实测**(全程零 GUI),编目于此,供上层"任何需求 → 匹配已集成能力"映射。

本会话实测确立的三大支柱(均经 _EXTAPI_ROOT_ / worker 总线直驱,见 EVOLUTION_NOTES):

  ① 天下器件库(LCSC/JLC 数百万元件,系统库免自建)
     lib_Device.search(kw) / searchByProperties / getByLcscIds([...])
     lib_Footprint/lib_Symbol/lib_3DModel/lib_Cbb.search、lib_PanelLibrary.search
     lib_LibrariesList.registerExtendLibrary(注册外部扩展库)

  ② 跨生态格式整合(KiCad/Altium/外部布线器 → JLC)
     sys_FormatConversion.convertAltiumDesignerLibrariesToEasyEDA{Single,Multi}File
     sys_FileManager.importProjectByProjectFile
     pcb_Document.importAutoRouteSesFile / importAutoRouteJsonFile / importAutoLayoutJsonFile
       (吃外部布线/布局成果,如 FreeRouting .ses)
     worker /mgr/projectWorker/import(整板 .epru 无损灌库,见 canvas_lowlevel)

  ③ 全链路制造闭环(原理图→网表→PCB→Gerber/BOM,程序化导出 + 比对)
     sch_Netlist/pcb_Net.getNetlist/setNetlist(JSON 网表读写)
     sch_ManufactureData.getNetlistFile/getBomFile/getSimulationNetlistFile
     pcb_ManufactureData.getNetlistFile/getBomFile/getGerberFile/getInteractiveBomFile/
                         getAltiumDesignerFile(导出为 Altium)
     sys_Tool.netlistComparison(网表差异比对)

  ④ 社区生态(立创开源广场,公开工程不受所有权门控)
     oshwhub 同源 /api/common/projects/{uuid}/...、/api/project/{uuid}
     sys_FileManager.getProjectFileByProjectUuid(<oshwhubUuid>) → 整包 .epro2

  ⑤ 工程结构管理(精确克隆/装配,worker 持久化)
     /mgr/projectWorker/{board,schematic,pcb,sheet,device}/delete(裸 uuid,落库)
     dmt_Board.getAllBoardsInfo / dmt_Project.createProject/openProject

每条端点在 ENDPOINTS 里标注 verified=True(本会话实测过)或 False(已定位待实证)。
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d


# --------------------------------------------------------------------------- #
# 资源接入编目(按 PCB 生命周期阶段组织)
# --------------------------------------------------------------------------- #
ENDPOINTS = {
    "器件库·天下元件": [
        ("lib_Device.search", "kw:str → [device...]", True),
        ("lib_Device.searchByProperties", "{props} → [device...]", False),
        ("lib_Device.getByLcscIds", "[lcscId...] → [device...]", True),
        ("lib_Footprint.search", "kw → [footprint...]", False),
        ("lib_Symbol.search", "kw → [symbol...]", False),
        ("lib_3DModel.search", "kw → [model...]", False),
        ("lib_LibrariesList.registerExtendLibrary", "注册外部扩展库", False),
    ],
    "跨生态格式整合": [
        ("sys_FormatConversion.convertAltiumDesignerLibrariesToEasyEDASingleFile",
         "Altium .SchLib/.PcbLib → .elibz2(实测 2符号/3封装)", True),
        ("sys_FormatConversion.convertAltiumDesignerLibrariesToEasyEDAMultiFiles",
         "Altium 库 → 多 .elibz2 数组", True),
        ("sys_FileManager.importProjectByProjectFile", "工程文件导入(JSON 桥丢二进制)", False),
        ("pcb_ManufactureData.getDsnFile", "→ Specctra .dsn(喂 FreeRouting)", True),
        ("pcb_Document.importAutoRouteSesFile", "FreeRouting .ses 回灌(实测 ret=true,布线改变)", True),
        ("pcb_Document.importAutoLayoutJsonFile", "外部布局结果导入", False),
        ("worker:/mgr/projectWorker/import", ".epru 整板无损灌库(正道)", True),
    ],
    "全链路制造闭环": [
        ("pcb_Net.getNetlist", "→ JSON 网表(version/components/designRule)", True),
        ("sch_ManufactureData.getNetlistFile", "→ .enet 文件", True),
        ("pcb_ManufactureData.getNetlistFile", "→ .enet 文件", True),
        ("pcb_ManufactureData.getBomFile", "→ BOM .xlsx", True),
        ("pcb_ManufactureData.getGerberFile", "→ Gerber .zip", True),
        ("pcb_ManufactureData.getAltiumDesignerFile", "→ Altium 工程 ZIP(.schdoc/.pcbdoc)", True),
        ("sys_Tool.netlistComparison", "网表差异比对", False),
    ],
    "社区生态·立创开源广场": [
        ("sys_FileManager.getProjectFileByProjectUuid", "公开工程整包 .epro2(不受门控)", True),
        ("oshwhub:/api/common/projects/{uuid}", "工程元数据/评论/状态(同源)", True),
    ],
    "工程结构管理·精确克隆": [
        ("worker:/mgr/projectWorker/board/delete", "持久化删板(裸 uuid)", True),
        ("worker:/mgr/projectWorker/schematic/delete", "持久化删原理图", True),
        ("worker:/mgr/projectWorker/pcb/delete", "持久化删 PCB", True),
        ("worker:/mgr/projectWorker/sheet/delete", "持久化删原理图页", True),
        ("dmt_Board.getAllBoardsInfo", "列全部板", True),
    ],
}


def print_registry():
    """打印资源接入编目(✓=本会话实测,·=已定位待实证)。"""
    for stage, eps in ENDPOINTS.items():
        print("\n■ %s" % stage)
        for name, desc, verified in eps:
            print("  %s %-58s %s" % ("✓" if verified else "·", name, desc))


# --------------------------------------------------------------------------- #
# 薄封装(经编辑器 CDP 会话直驱)
# --------------------------------------------------------------------------- #
def _ws(ws=None):
    return ws or d._editor_session()


def search_devices(keyword, ws=None, timeout=30):
    """①天下器件:按关键词检索系统/LCSC 器件库,返回器件记录列表。"""
    return d.call_eda(_ws(ws), "lib_Device.search", keyword, timeout=timeout) or []


def devices_by_lcsc(lcsc_ids, ws=None, timeout=30):
    """①天下器件:按 LCSC 编号(如 ['C25804'])直取器件记录,供放件/落库。"""
    return d.call_eda(_ws(ws), "lib_Device.getByLcscIds", list(lcsc_ids), timeout=timeout) or []


def get_pcb_netlist(ws=None, timeout=40):
    """③制造闭环:取当前 PCB 的 JSON 网表(需 PCB 文档已打开)。"""
    return d.call_eda(_ws(ws), "pcb_Net.getNetlist", timeout=timeout)


# File 类导出端点 → 下载为 bytes(File.arrayBuffer → base64 过桥)
_FILE_EXPORTS = {
    "sch_netlist": "sch_ManufactureData.getNetlistFile",
    "pcb_netlist": "pcb_ManufactureData.getNetlistFile",
    "bom": "pcb_ManufactureData.getBomFile",
    "gerber": "pcb_ManufactureData.getGerberFile",
    "altium": "pcb_ManufactureData.getAltiumDesignerFile",
}


def export_file(kind, ws=None, timeout=60):
    """③制造闭环:导出 netlist/bom/gerber/altium 为 (filename, bytes)。

    kind ∈ {sch_netlist, pcb_netlist, bom, gerber, altium}。需相应文档已打开。
    """
    method = _FILE_EXPORTS[kind]
    js = (
        "(async()=>{var r=await window._EXTAPI_ROOT_.%s();"
        "if(!r)return JSON.stringify({ok:false});"
        "var b=new Uint8Array(await r.arrayBuffer());var s='';"
        "for(var i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);"
        "return JSON.stringify({ok:true,name:r.name,b64:btoa(s)});})()" % method
    )
    v, e = d.evaluate(_ws(ws), js, await_promise=True, timeout=timeout)
    if e:
        raise RuntimeError("export_file %s -> %s" % (kind, e))
    obj = json.loads(v)
    if not obj.get("ok"):
        return None, None
    return obj["name"], base64.b64decode(obj["b64"])


def import_autoroute_ses(ses_bytes, ws=None, timeout=120):
    """②跨生态:把 FreeRouting 等外部布线器产出的 Specctra .ses 回灌当前 PCB。
    ses_bytes:bytes 或 str(路径)。返回端点结果(实测 True 表应用成功)。需 PCB 文档已打开。"""
    if isinstance(ses_bytes, str) and os.path.exists(ses_bytes):
        ses_bytes = open(ses_bytes, "rb").read()
    b64 = base64.b64encode(ses_bytes).decode()
    js = (
        "(async()=>{try{var bin=atob(%s);var a=new Uint8Array(bin.length);"
        "for(var i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);"
        "var file=new File([a],'route.ses',{type:'text/plain'});"
        "var r=await window._EXTAPI_ROOT_.pcb_Document.importAutoRouteSesFile(file);"
        "return JSON.stringify({ok:true,ret:(r===undefined?'undefined':r)});"
        "}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
        % json.dumps(b64)
    )
    v, e = d.evaluate(_ws(ws), js, await_promise=True, timeout=timeout)
    if e:
        raise RuntimeError("import_autoroute_ses -> %s" % e)
    return json.loads(v)


def convert_altium_library(lib_bytes, filename="lib.SchLib", multi=False, ws=None, timeout=120):
    """②跨生态:把 Altium 库(.SchLib/.PcbLib/.IntLib)转为 EasyEDA Pro 库 .elibz2。
    lib_bytes:bytes 或 str(路径)。返回结果摘要(SingleFile→File,MultiFiles→数组)。"""
    if isinstance(lib_bytes, str) and os.path.exists(lib_bytes):
        filename = os.path.basename(lib_bytes)
        lib_bytes = open(lib_bytes, "rb").read()
    b64 = base64.b64encode(lib_bytes).decode()
    method = ("convertAltiumDesignerLibrariesToEasyEDAMultiFiles" if multi
              else "convertAltiumDesignerLibrariesToEasyEDASingleFile")
    js = (
        "(async()=>{try{var bin=atob(%s);var a=new Uint8Array(bin.length);"
        "for(var i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);"
        "var file=new File([a],%s);"
        "var r=await window._EXTAPI_ROOT_.sys_FormatConversion.%s(file);"
        "if(Array.isArray(r))return JSON.stringify({ok:true,arrLen:r.length});"
        "if(r&&r.arrayBuffer){var b=new Uint8Array(await r.arrayBuffer());"
        "return JSON.stringify({ok:true,fileName:r.name,bytes:b.length});}"
        "return JSON.stringify({ok:true,type:typeof r});"
        "}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
        % (json.dumps(b64), json.dumps(filename), method)
    )
    v, e = d.evaluate(_ws(ws), js, await_promise=True, timeout=timeout)
    if e:
        raise RuntimeError("convert_altium_library -> %s" % e)
    return json.loads(v)


def get_community_epro2(oshwhub_uuid, ws=None, timeout=60):
    """④社区生态:取立创开源广场公开工程整包 .epro2(bytes)。"""
    js = (
        "(async()=>{var f=await window._EXTAPI_ROOT_.sys_FileManager"
        ".getProjectFileByProjectUuid(%s);var b=new Uint8Array(await f.arrayBuffer());"
        "var s='';for(var i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);"
        "return btoa(s);})()" % json.dumps(oshwhub_uuid)
    )
    v, e = d.evaluate(_ws(ws), js, await_promise=True, timeout=timeout)
    if e:
        raise RuntimeError("get_community_epro2 -> %s" % e)
    return base64.b64decode(v)


if __name__ == "__main__":
    print_registry()
