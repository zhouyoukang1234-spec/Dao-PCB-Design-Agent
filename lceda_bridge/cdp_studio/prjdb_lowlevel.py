#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""底层字典直驱 —— 绕过 _EXTAPI_ROOT_ 与一切 GUI,直达嘉立创EDA Pro 的工程数据层(PrjDB)。

★ 反者道之动·从底层突破(会话实证):
  - 表层 GUI / computer 工具放件 = 逻辑错误,弃。
  - `window._EXTAPI_ROOT_` 只是 rpc 包装(转发到 worker,大量处理器在自动化上下文未接通)。
  - 真底层 = 编辑器自己用的**工程数据库 rpc**,主线程内注册、经全局总线 `window._MSG_BUS_` 可直接调:
        ye.messageBus === window._MSG_BUS_        (bundle 实证)
    数据层两套 topic 命名空间:
      /PrjDB/<entity>/<op>            —— 持久化数据库(主线程内 z(topic,handler) 注册,handler 委派
                                         给 J(r)=Ja.getInstance().get(projectId) 的工程DB对象);
                                         读类(getData/getAllArrDatas/getAllPrimaryKeys)实证可用。
      /mgr/projectWorker/<entity>/<op> —— 活动文档 worker(this.project.workerBus=Bn,私有实例,
                                         全局总线打不到;EXTAPI 即其薄包装)。
  - setCanvas 签名(bundle 实证):
        z(te.SHEET.SET_CANVAS, async(t,s,r)=> (await J(r).sheet.setCanvas(t,s)).success)
        t=sheetUuid, s=canvasData(图元记录), r=projectId(缺省 ye.currentProject.projectId)
    ⇒ 底层写: _MSG_BUS_.rpcCall("/PrjDB/sheet/setCanvas",[uuid, canvasData])

★ 工程数据格式(.epro2 解包实证):.epro2 = zip{ project2.json, <title>.epru, IMAGE/ }。
  .epru = 逐行 `{header}||{payload}|` 的多文档记录流(DOCHEAD 切分子文档:
  FOOTPRINT/SYMBOL/DEVICE/BOARD/SCH/SCH_PAGE/PCB/CONFIG/PANEL/BLOB)。
  关键图元记录:PART(原理图器件)/COMPONENT(PCB封装实例)/PIN/NET/PAD_NET/PRIMITIVE/POLY/PAD/LINE...
  ★ 库符号/封装/器件**内联嵌入**工程 → 自包含设计无需库后端拉取(这正是 EXTAPI `create` 卡死之因)。

★ 非阻塞 rpc 调用法(必须):页内 fire-and-poll —— rpc 无回执时 awaitPromise 会冻结整条 CDP,
  故 .then 写 window.__rr,再分轮询读,绝不在 evaluate 里 awaitPromise 等 rpc。
"""
import json
import time
import sys

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d  # noqa: E402

# 全局总线名(window 上)。/PrjDB/* 在主线程注册,用 _MSG_BUS_ 即可。
DEFAULT_BUS = "_MSG_BUS_"


def rpc(ws, topic, args=None, bus=DEFAULT_BUS, wait=12):
    """非阻塞调用工程数据层 rpc。返回 (ok_value, err_str)。

    fire-and-poll:页内 .then 写 window.__rr;分轮询读,避免 awaitPromise 冻结 CDP。
    """
    args = args if args is not None else []
    fire = (
        "(()=>{window.__rr=0;try{var B=window[%s];"
        "if(!B||!B.rpcCall){window.__rr={err:'no bus '+%s};return 1;}"
        "B.rpcCall(%s,%s).then(r=>{window.__rr={ok:r}}).catch(e=>{window.__rr={err:String(e&&e.message||e)}});"
        "}catch(e){window.__rr={err:'throw '+String(e)}}return 1;})()"
        % (json.dumps(bus), json.dumps(bus), json.dumps(topic), json.dumps(args))
    )
    d.evaluate(ws, fire, await_promise=False, timeout=8)
    for _ in range(wait):
        time.sleep(1)
        v, _e = d.evaluate(
            ws,
            "(()=>window.__rr===0?'pending':(window.__rr.ok!==undefined?'OK':JSON.stringify(window.__rr)))()",
            await_promise=False,
            timeout=8,
        )
        if v and v != "pending":
            if v == "OK":
                full, _e2 = d.evaluate(
                    ws,
                    "(()=>{try{return JSON.stringify(window.__rr.ok);}catch(e){return '__BIG__:'+e;}})()",
                    await_promise=False,
                    timeout=15,
                )
                return full, None
            return None, v
    return None, "TIMEOUT(no reply)"


# --- 工程数据库 topic 常量(bundle 反出·实证可调的读类) --------------------- #
class T:
    PCB_GET = "/PrjDB/pcb/getData"
    PCB_KEYS = "/PrjDB/pcb/getAllPrimaryKeys"
    PCB_SET_CANVAS = "/PrjDB/pcb/setCanvas"
    PCB_GET_CANVAS = "/PrjDB/pcb/getCanvas"
    SCH_GET = "/PrjDB/schematic/getData"
    SCH_ALL = "/PrjDB/schematic/getAllArrDatas"
    SCH_ADD = "/PrjDB/schematic/addData"
    SHEET_ALL = "/PrjDB/sheet/getAllArrDatas"
    SHEET_GET = "/PrjDB/sheet/getData"
    SHEET_ADD = "/PrjDB/sheet/addData"
    SHEET_SET_CANVAS = "/PrjDB/sheet/setCanvas"
    SHEET_GET_CANVAS = "/PrjDB/sheet/getCanvas"
    DEVICE_GET = "/PrjDB/device/getData"
    DEVICE_CREATE = "/PrjDB/device/createData"
    SYMBOL_GET = "/PrjDB/symbol/getData"
    SYMBOL_ADD = "/PrjDB/symbol/addData"
    FOOTPRINT_GET = "/PrjDB/footprint/getData"
    FOOTPRINT_ADD = "/PrjDB/footprint/addData"


if __name__ == "__main__":
    import eda_flow

    f = eda_flow.Flow()
    print("pcb keys:", rpc(f.ws, T.PCB_KEYS, []))
    print("sheets :", (rpc(f.ws, T.SHEET_ALL, [])[0] or "")[:200])
