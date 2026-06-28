#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""嘉立创EDA Pro · 活动文档 worker 底层 canvas 读/写(弃 GUI、弃 EXTAPI 包装)。

★ 本模块是上一对话遗留的"最后核心模块"的根治成果(会话实证):
  确定性建板的真正入口 = 构造图元 canvas 直接 setCanvas 灌入工程数据库 → 保存 → 落库持久化。
  全程不经 GUI、不经合成鼠标、不经库后端拉取,反者道之动,从底层突破一切。

═══ 逆向出的底层事实(全部页内实证) ═══════════════════════════════════════════

1. 私有工程 worker 总线的真实位置(上一对话"全局总线打不到"的缺口):
       workerBus = Bn(`/${window._TAB_ID_}/project/${projectUuid}`)
       function Bn(e){ return self[e] = self[e] || new BroadcastChannelMessageBus(e) }
   ⇒ 实际总线对象 = self["/<TAB_ID>/project/<projectUuid>"],其 .rpcCall 直达
     `/mgr/projectWorker/*`(377 topic)。须先打开该工程的任一文档,worker 方才实例化。

2. worker 端 rpc 真实入参(从 project-worker.js 反出 + 实证校准):
     /mgr/projectWorker/sheet/getCanvas      参数 {doc:[uuid]}        → {success, data:{...元数据}}
     /mgr/projectWorker/sheet/getAllArrData   参数 <schematicUuid>     → 该 schematic 下全部 sheet 记录
                                              (注意:按 a.schematic===s 过滤,传 sheetUuid 会得 [])
     /mgr/projectWorker/sheet/extractCanvas   参数 <uuid>(裸串)       → {dataSet:{devices,symbols,
                                              footprints,blobs}, parentIds:{...}}
     /mgr/projectWorker/sheet/buildString     参数 {data:{uuid,...},keepUUID:true}
                                              → {result:{uuid,dataStr,updateTime}}
                                              (只序列化 data 里给定的内容,不读 worker 已载图元)
     /mgr/projectWorker/sheet/setCanvas       参数 {uuid:<sheetUuid>, canvas:<dataStr 记录块>}
                                              → {success:true}   ★ 底层直写入口,实证落库持久化
   pcb/symbol/footprint/device 各 entity 同构(把 sheet 换成对应名)。

3. canvas dataStr(记录块)格式 = .epru 同源:逐行 `{header}||{payload}|`,
   DOCHEAD 切分子文档,图元记录 PART/PIN/NET/COMPONENT/PAD/WIRE/LINE/ATTR/META...
   可经 sys_FileManager.getProjectFileByProjectUuid(uuid) 取整工程 .epro2(zip)解包获得真实样本。

4. 非阻塞调用法(必须):rpc 无回执时页内 awaitPromise 会冻结整条 CDP。
   故一律 fire-and-poll:.then 写 window.__wr,分轮询读。
"""
import json
import time
import sys

sys.path.insert(0, ".")
import dao_eda_cdp_driver as d  # noqa: E402


def worker_bus_expr(ws, project_uuid):
    """返回该工程 worker 总线在页内的 JS 取值表达式 `self["..."]`,未就绪返回 None。

    须先 open_document 打开该工程任一文档,worker 总线方才在 self 上实例化。
    """
    key, _ = d.evaluate(
        ws,
        "(()=>Object.keys(self).filter(k=>/\\/project\\//.test(k))"
        ".find(k=>k.indexOf(%s)>=0)||null)()" % json.dumps(project_uuid),
        await_promise=False,
        timeout=8,
    )
    if not key:
        return None
    return "self[%s]" % json.dumps(key)


def wrpc(ws, bus_expr, topic, args=None, wait=15):
    """对任意总线表达式 fire-and-poll 调 rpc。返回 (full_json_str|None, err|None)。

    full_json_str 形如 'LEN<n>::<前 n 字符>' 用于快速查看;需完整对象时用 wrpc_full。
    """
    args = args if args is not None else []
    fire = (
        "(()=>{window.__wr=0;try{var B=%s;"
        "if(!B||!B.rpcCall){window.__wr={err:'no bus'};return 1;}"
        "B.rpcCall(%s,%s).then(r=>{window.__wr={ok:r}})"
        ".catch(e=>{window.__wr={err:String(e&&e.message||e)}});"
        "}catch(e){window.__wr={err:'throw '+String(e)}}return 1;})()"
        % (bus_expr, json.dumps(topic), json.dumps(args))
    )
    d.evaluate(ws, fire, await_promise=False, timeout=8)
    for _ in range(wait):
        time.sleep(1)
        v, _e = d.evaluate(
            ws,
            "(()=>window.__wr===0?'pending':"
            "(window.__wr.ok!==undefined?'OK':JSON.stringify(window.__wr)))()",
            await_promise=False,
            timeout=8,
        )
        if v and v != "pending":
            if v == "OK":
                full, _e2 = d.evaluate(
                    ws,
                    "(()=>{try{var s=JSON.stringify(window.__wr.ok);"
                    "return s===undefined?'OK_UNDEF':('LEN'+s.length+'::'+s.slice(0,600));}"
                    "catch(e){return 'BIG:'+e;}})()",
                    await_promise=False,
                    timeout=15,
                )
                return full, None
            return None, v
    return None, "TIMEOUT(no reply)"


def wrpc_full(ws):
    """取上一次 wrpc 的完整 ok 对象(JSON 字符串),供需要全量返回时调用。"""
    full, _ = d.evaluate(
        ws,
        "(()=>{try{return JSON.stringify(window.__wr.ok);}catch(e){return null;}})()",
        await_promise=False,
        timeout=20,
    )
    return full


# --- 高层封装(已实证的 worker 端点) ----------------------------------------- #

def get_canvas(ws, bus, sheet_uuid):
    """读 sheet canvas 元数据。参数 {doc:[uuid]}。"""
    return wrpc(ws, bus, "/mgr/projectWorker/sheet/getCanvas", {"doc": [sheet_uuid]})


def get_all_arr_data(ws, bus, schematic_uuid):
    """列出某 schematic 下全部 sheet 记录。参数 = schematic uuid(裸串)。"""
    return wrpc(ws, bus, "/mgr/projectWorker/sheet/getAllArrData", schematic_uuid)


def extract_canvas(ws, bus, sheet_uuid):
    """提取 sheet 的 dataSet(内联库)与 parentIds。参数 = uuid(裸串)。"""
    return wrpc(ws, bus, "/mgr/projectWorker/sheet/extractCanvas", sheet_uuid)


def set_canvas(ws, bus, sheet_uuid, canvas_datastr):
    """★ 底层直写:把 canvas 记录块灌入 sheet。参数 {uuid, canvas}。

    canvas_datastr = .epru 同源记录块(逐行 {header}||{payload}|)。
    返回 {success:true} 即写入成功;随后 sch_Document.save 落库持久化。
    """
    return wrpc(
        ws, bus, "/mgr/projectWorker/sheet/setCanvas",
        {"uuid": sheet_uuid, "canvas": canvas_datastr},
    )


def set_pcb_canvas(ws, bus, pcb_uuid, canvas_datastr):
    """PCB 侧底层直写。参数 {uuid, canvas}(与 sheet 同构)。"""
    return wrpc(
        ws, bus, "/mgr/projectWorker/pcb/setCanvas",
        {"uuid": pcb_uuid, "canvas": canvas_datastr},
    )


def import_project(ws, bus, target_project_uuid, epru_str, images=None, wait=180):
    """★★★ 整板底层灌库:把一整份 .epru(成品板全部子文档)经 worker `import`
    端点一次性写入目标工程 —— 弃 EXTAPI、弃 GUI、二进制不丢(走 worker 总线非 JSON 桥)。

    逆向自 project-worker.js:
        workerBus.rpcService(public.import, t => instance.import(t))
        import(s){ new Xd(s,this).start() }       # Xd = ImportTarget(批量粘贴式导入)
        Xd: {uuid, datas, structure} ──►
            structure==='export3.0' 或 typeof datas.dataStr==='string'
              → parseExport3_0: Mn({str:dataStr}) 解析 .epru → gc(...) 写入工程数据库
    入参:
        target_project_uuid  目标(空)工程 uuid;须先 createProject + 打开任一文档使 worker 实例化
        epru_str             解包 .epro2 得到的 .epru 全文(逐行 {header}||{payload}|)
    返回:wrpc 结果。成功为 {success:true, result:{map:{symbolMap,deviceMap,
        footprintMap,schematicMap,pcbMap,pathMap,...}}}(新旧 uuid 映射表)。

    ★ 实证:NE555 Blinker 成品板(20 子文档)→ 全新空工程,克隆出的原理图器件
      (NE555 八脚符号 + 电阻)与 PCB(铜层/焊盘/封装)在编辑器中完整渲染。
    """
    args = {
        "uuid": target_project_uuid,
        "datas": {"dataStr": epru_str, "images": images or {}},
        "structure": "export3.0",
    }
    return wrpc(ws, bus, "/mgr/projectWorker/import", args, wait=wait)


if __name__ == "__main__":
    import eda_flow

    f = eda_flow.Flow()
    ws = f.ws
    print("usage: open a project/doc, then call get_canvas/set_canvas with its worker bus.")
    print("see EVOLUTION_NOTES.md 会话 2f 节 for the validated full read/write chain.")
