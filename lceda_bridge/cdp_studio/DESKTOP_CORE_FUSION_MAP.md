# 嘉立创EDA本体·进程级融合地图(Core Fusion Map v0)

> 反者道之动。之前的一切(CDP 调 `_EXTAPI_ROOT_`)只是软件本体**喂给外部的一层受控表皮**,
> 注定盲探 + 大规模试错。本文把地基从"表皮 API"下沉到"**进程本体**",以**活体真值**
> (运行时 CDP introspection)+ **明文源码测绘**(客户端未打包裸放于磁盘)建立唯一真理源。
> 仅读/勘察,未改动本体。

## 0. 决定性事实(本轮活体坐实)

| 事实 | 值 | 证据 |
|---|---|---|
| 客户端形态 | Electron 36.3.1 / Chrome 136 / V8 13.6 / Node 主进程 | `curl :29230/json/version` |
| 版本 | JLCEDA_Pro `3.2.149.88089769` | `resources/app/package.json` |
| **源码形态** | **明文裸放于磁盘,非 asar 二进制** | `resources/app/assets/**/*.js` 可直接 `read`/`grep` |
| 主进程入口 | `resources/app/app.js`(`require("electron")`,fs/path) | `package.json.main` |
| 源码可写 | `pcb.js` 等为 `-rw-r--r--`(**可改**) | `test -w` |
| 完整性护栏 | 各扩展 `extension.json` 带 `innerSign` + 每文件 md5 | 静改前须先评估签名校验是否强制 |

## 1. 三层本体结构(层层向下)

```
┌────────────────────────────────────────────────────────────────┐
│ L0 表皮  window._EXTAPI_ROOT_ = new tg("eda")   ← 之前唯一入口   │
│   活体实测 94 命名空间 / 752 方法(facade,官方白名单子集)        │
│   本质是门面类 tg,把调用转发到内部消息总线                        │
├────────────────────────────────────────────────────────────────┤
│ L1 总线  extensionApiMessageBus2 / sys_MessageBus                │
│   facade 上直接暴露 sys_MessageBus,18 法:                        │
│     publish/subscribe/push/pull(Async)/rpcCall/rpcService ...    │
│   主线程↔worker 线程的真实控制面。静态测绘得 **1140 个 RPC 主题** │
│   (远大于 752):/engine/* /pcb/3d/* /PrjDB/* /mgr/projectWorker/*│
│    /model/export/* ... 深入几何/3D/DB/模型导出 worker             │
├────────────────────────────────────────────────────────────────┤
│ L2 引擎  pro-pcb/pcb.js(10.8MB)/ sch.js / drcWorker / worker    │
│   内部命令管理器 je.executeCommand(pcb.js 内 193 处调用)         │
│   addCommand 786 处(编辑事务/undo 栈的命令对象)                  │
│   驱动**全部 GUI 菜单/快捷键/属性编辑**——"用户能做但 API 不开放" │
│   的能力都在此层;模块作用域内(不在 window),需 hook 才能触达     │
└────────────────────────────────────────────────────────────────┘
```

## 2. 两条已坐实的深融路径

### 路径甲(非破坏·即刻可用):`sys_MessageBus` 直取内部 RPC
- facade 已暴露 `sys_MessageBus.rpcCall/publish/subscribe`——**无需 patch、无需重启**。
- 内部 1140 主题构成真实服务目录(见 `_core_rpc_topics.txt`)。
- 做法:经 CDP 调 `_EXTAPI_ROOT_.sys_MessageBus.rpcCall(topic, payload)` 触达
  facade 未封装的内部服务(3D 导出/几何/字体/DB/工程 worker 等)。
- 风险低:走本体自己的总线协议,不碰磁盘、不碰签名。
- **实测纠偏**:直接 `sys_MessageBus.rpcCall("LocaleCurrFetch",{})` 会**挂起不返回**——
  证明这批 RPC 服务并非注册在**默认公共总线**上,而在**私有/worker 作用域总线**
  (`createPrivateMessageBus(channel)` 或 worker 侧 `rpcService`)。故路径甲的正解是:
  先定位每个主题所属的**私有总线频道**(源码里 `createPrivateMessageBus("<ch>")`),
  拿对应 bus 句柄再 `rpcCall`。这一步已缩小为"频道匹配"问题,非玄学。

### 路径乙(代码级·最深):写盘裸源 + 注入引导钩子
- 源码明文可写 → 在本体自身 bootstrap 注入极小钩子,把 L2 的内部命令管理器
  `je` / 模块注册表挂到 `window.__DAO_CORE__`,则**全部 GUI 内部命令**(执行/属性/
  菜单)即可经 CDP 直调,达成前后端一切可改。
- **拦路**:`extension.json.innerSign` + 文件 md5 可能触发加载期完整性校验。
  落地前须先判定:该校验是否强制、在渲染层还是 Node 主进程、可否随钩子一并调和。
- 属"进程级融合"终态,收益最大,须谨慎不劣化。

## 3. 下一步(推进序)
1. 活体枚举 `sys_MessageBus` 可达 RPC(路径甲):挑几个高价值主题实调坐实
   (如 `/engine/capture/png`、`/model/export/pcb/step2`、`/PrjDB/*/getData`)。
2. 判定 `innerSign` 完整性校验的强制性与作用点(决定路径乙可行性)。
3. 建 `dao_core.py`:在 `dao_rpc_driver` 之下再沉一层"总线直取 + 命令直调"原语,
   把"本体一切工具"收敛为可编程调用,替代盲探试错。

*道法自然 · 无为而无不为:得其母以知其子,复守其母。*
