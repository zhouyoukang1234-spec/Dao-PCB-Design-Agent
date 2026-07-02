# DAO AI IDE · 云端 Agent 反向接入文档

> 本文档供任何云端 Agent(Devin Cloud / 其他 LLM Agent)读取后**直接接入**嘉立创EDA专业版底层,
> 拥有与外接第三方 API 模型完全相同的全部底层能力。参照 Devin Remote 插件同源逻辑:
> 功能自足 + 反向接入文档 + 可搭配内网穿透板块(DAO Bridge)跨机接入。

## 一、系统构成(两套入口·同一底层)

| 入口 | 使用者 | 通道 |
|---|---|---|
| A. IDE 面板(原生扩展) | 人类用户 + 外接第三方API模型(DeepSeek/MiMo等) | 面板内 tool-calling → EXTAPI |
| B. CDP 直驱 | 云端 Agent(你) | WebSocket CDP :29230 → 同一 EXTAPI |

两套入口驱动**同一个引擎**,状态实时互通。

## 二、快速接入(Agent 三步)

前置:EDA 桌面端已以 `--remote-debugging-port=29230 --remote-allow-origins='*'` 启动。
若跨机接入,先经 DAO Bridge 内网穿透(见知识库「DAO Bridge 内网穿透接入文档」)把 29230 转发到位。

```bash
# 1. 感知全貌(任何任务开始前必做,像看一个文件一样看到整个工程)
python3 lceda_bridge/dao_ai_ide/pcb_digest.py            # markdown 报告
python3 lceda_bridge/dao_ai_ide/pcb_digest.py --json     # 结构化 JSON
python3 lceda_bridge/dao_ai_ide/pcb_digest.py --full     # 附全部图元坐标明细

# 2. 任意 EXTAPI 调用(94 命名空间 / 749 方法)
python3 - <<'PY'
import sys; sys.path.insert(0, 'lceda_bridge/cdp_studio')
import dao_eda_cdp_driver as d
ws = d.connect_editor(29230)
out, err = d.call_eda(ws, 'pcb_PrimitiveVia.create', ["", 3200, 3200, 11.8, 23.6])
print(out, err)
PY

# 3. 用真实外接模型走面板全链路(代替用户发消息)
DAO_MSG='先调 project_digest 看全貌,再放一个过孔并跑 DRC' \
  python3 lceda_bridge/dao_ai_ide/real_drive.py
```

## 三、核心已验证方法签名(坐标单位 mil)

| 操作 | 调用 |
|---|---|
| 工程全貌 | 面板工具 `project_digest` / 脚本 `pcb_digest.py` |
| 放过孔 | `pcb_PrimitiveVia.create` args=`[net, x, y, holeD, D]` 如 `["",3000,3000,11.8,23.6]` |
| 统计图元 | `pcb_Primitive<Type>.getAll` args=`[]`(Type∈Component/Via/Line/Pad/Arc/…) |
| 跑 DRC | `pcb_Drc.check` args=`[]`(返回 false 即 0 违规) |
| 存盘 | `pcb_Document.save` args=`[]` |
| 弹提示 | `sys_Message.showToastMessage` args=`[文本]` |
| 打开板 | `dmt_EditorControl.openDocument` args=`[pcbUuid]` |
| 制造数据 | `pcb_ManufactureData.getGerberFile/getBomFile/getPickAndPlaceFile` |

完整目录见 `lceda_bridge/cdp_studio/extapi_full_catalog.json` 与 `EXTAPI_REFERENCE.md`。

## 四、面板(入口A)内部协议 — 供接管/自动化

- 扩展安装:`python3 lceda_bridge/dao_ai_ide/install_eext.py`(程序化装入 IndexedDB,重启生效)
- 模型配置 localStorage 键(origin=https://client):
  - `dao.ai.ide.models` = `[{id,name,base,key,model,temp}]`(OpenAI 兼容 /chat/completions,须 https)
  - `dao.ai.ide.activeModel` / `dao.ai.ide.sessions` / `dao.ai.ide.prompts`
- 面板 iframe 为 blob: 源;注消息:iframe 内 `#input` 赋值 + dispatch input + `#send.click()`
- 面板 AI 工具集:`project_digest` / `get_context` / `eda_call(namespace,method,args)` / `toast`
- 收敛判据:面板 busy=false 且最后一条消息 role=assistant(参考 `real_drive.py` 轮询实现)

## 五、感知-行动-验证闭环(务必遵循)

1. **感知**:`project_digest` 取全貌 → 明确当前板/层/网络/器件/图元/DRC 状态
2. **行动**:最小步 EXTAPI 调用(create/modify/delete)
3. **验证**:再次 digest 或 getAll 比对增量;关键节点跑 `pcb_Drc.check`
4. **存证**:`pcb_Document.save` + 截图(`dmt_EditorControl.getCurrentRenderedAreaImage`)

盲人摸象是大忌:任何多步任务,每 3~5 步行动后必须重新感知一次全貌。
