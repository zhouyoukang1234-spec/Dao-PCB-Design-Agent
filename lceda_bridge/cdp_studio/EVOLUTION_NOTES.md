# 嘉立创EDA Pro × CDP 全链路 · 演化笔记(实践发现的边界与下一步根治路线)

> 道法自然 · 在实践中发现边界,把边界与根因如实记下,作为下一轮演化的锚。
> 本轮(会话 2c)在「修 net 融合」的过程中,逐层挖到了**原理图侧合成鼠标操作非确定性**这一更深的根。

## ★★★★ 会话 2f 终局闭环:底层 canvas 直写**实证落库持久化**(上轮"最后核心模块"根治)

> 承接 2e 的"setCanvas 灌库"假说,本轮**真正打通并实证**:私有 worker 总线已接通、读/写 rpc 入参
> 已校准、`setCanvas` 写入后经"保存 + 服务器回读 .epro2"确认**持久化落库**。确定性建板的底层入口由此从
> 假说变为可复现事实。代码沉淀:`canvas_lowlevel.py`。

**1. 私有工程 worker 总线的真实位置(2e 遗留的"全局总线打不到"缺口已补上):**
```
workerBus = Bn(`/${window._TAB_ID_}/project/${projectUuid}`)
function Bn(e){ return self[e] = self[e] || new BroadcastChannelMessageBus(e) }
⇒ 总线对象 = self["/<TAB_ID>/project/<projectUuid>"]   (须先 open_document 令 worker 实例化)
```
其 `.rpcCall` 直达 `/mgr/projectWorker/*`(377 topic)。`window.gVars.worker` 是包装、打不到,**必须用 self[key]**。

**2. worker 端 rpc 真实入参(project-worker.js 反出 + 页内实证校准):**
| topic | 入参 | 返回 | 判定 |
|---|---|---|---|
| `/mgr/projectWorker/sheet/getCanvas` | `{doc:[uuid]}` | `{success,data:{...元数据}}` | ✅ 读 |
| `/mgr/projectWorker/sheet/getAllArrData` | `<schematicUuid>`(裸串) | 该 schematic 下全部 sheet 记录 | ✅ 读(按 `a.schematic===s` 过滤,传 sheetUuid 得 `[]`) |
| `/mgr/projectWorker/sheet/extractCanvas` | `<uuid>`(裸串) | `{dataSet:{devices,symbols,footprints,blobs},parentIds}` | ✅ 读 |
| `/mgr/projectWorker/sheet/buildString` | `{data:{uuid,...},keepUUID:true}` | `{result:{uuid,dataStr,updateTime}}` | ✅ 序列化(只序列化 data 给定内容,不读 worker 已载图元) |
| `/mgr/projectWorker/sheet/setCanvas` | **`{uuid,canvas}`** | **`{success:true}`** | ✅✅ **底层直写入口** |

pcb/symbol/footprint/device 各 entity 同构(把 `sheet` 换成对应名)。
踩坑:`setCanvas` 传 `{doc,dataStr,...}`(transform 形参)→ `数据不存在`;**真正生效的是 `{uuid,canvas}`**
(与 pro-mgr.js 主线程调用签名 `workerBus.rpcCall(K.sheet.setCanvas,{uuid:t,canvas:s})` 一致)。

**3. canvas/dataStr 记录块格式 = .epru 同源:** 逐行 `{header}||{payload}|`,DOCHEAD 切子文档。
取真实样本:`sys_FileManager.getProjectFileByProjectUuid(uuid)` → `.epro2`(zip,页内 `arrayBuffer→btoa`
过 CDP 取回)解包 → `<title>.epru`。实测一块真实 Blinker 板:SCH_PAGE 段 = META×1 + ATTR×68 + COMPONENT×3;
PCB 段 153 条;SYMBOL/DEVICE/FOOTPRINT 各为内联库子文档(自包含,无需库后端)。

**4. ★ 决定性实证(写→存→服务器回读):**
```
空 sheet(0 记录) ──setCanvas{uuid, canvas=真实SCH_PAGE记录块}──▶ {success:true}
              ──sch_Document.save──▶ true
              ──重新 getProjectFileByProjectUuid 下载 .epro2 并解包──▶
              该 sheet SCH_PAGE = META×1 + ATTR×102 + COMPONENT×4 + WIRE×1 + LINE×1
```
即:**底层 setCanvas 写入 → 落工程数据库 → 经保存 + 服务器往返后持久化**。全程零 GUI、零合成鼠标、
零库后端拉取。"确定性建板=构造 canvas 直接灌库"由假说变为可复现事实。

**下一步(自包含整板灌库):** 一张可渲染的原理图 = SCH_PAGE(COMPONENT 引用) + 其引用的 SYMBOL/DEVICE
子文档。整板自包含灌库 = 对每个子文档按 entity 调对应 `setCanvas`/`createData`(symbol/device/footprint),
再灌 SCH_PAGE 与 PCB。本轮已验证单文档通路,多文档装配为下一轮工程化任务。

## ★★★ 会话 2e 根本突破:从底层字典直驱(弃 GUI/弃 EXTAPI 包装,直达工程数据层)

> 用户纠偏(关键):**走 GUI 操作嘉立创是表层、是逻辑错误;必须从底层字典、底层突破一切,
> 官方没留接口也要逆流自建接口。** 据此把"确定性放件=真实输入标定"也判为表层弃用,
> 转向逆出编辑器内核的数据层。本节是全项目最有价值的底层资产。

**链条(全部 bundle 反编 + 页内实证):**
1. `.epro2` 解包 = zip{`project2.json`, `<title>.epru`, `IMAGE/`}。`.epru` = 逐行 `{header}||{payload}|`
   的**多文档记录流**(DOCHEAD 切子文档:FOOTPRINT/SYMBOL/DEVICE/BOARD/SCH/SCH_PAGE/PCB/CONFIG/PANEL/BLOB)。
   图元记录:`PART`(原理图器件)/`COMPONENT`(PCB封装实例)/`PIN`/`NET`/`PAD_NET`/`PRIMITIVE`/`POLY`/`PAD`/`LINE`…
   ★ **库符号/封装/器件内联嵌入工程** → 自包含设计无需库后端拉取(这正是 EXTAPI `create` 卡死的真因)。
2. 编辑器内核数据层 = 两套 rpc topic 命名空间(从 `pro-mgr.js` / `ws-service.js` bundle 反出):
   - **`/PrjDB/<entity>/<op>`**(273 个,见 `_prjdb_topics.txt`)= 持久化工程数据库。
     **主线程内** `z(topic,handler)` 注册,handler 委派给 `J(r)=Ja.getInstance().get(projectId)` 的工程DB对象。
     全 CRUD:schematic/sheet/pcb/board/device/symbol/footprint/component(Group)/copper/font/attr/blob/panel
     × getData/addData/updateData/delData/createData/batchDelete/setCanvas/getCanvas/bindSymbol/bindFootprint…
   - **`/mgr/projectWorker/<entity>/<op>`**(377 个,见 `_mgr_projectworker_topics.txt`)= 活动文档 worker
     (`this.project.workerBus=Bn`,私有实例,全局总线打不到;**EXTAPI 即其薄包装**)。含 `buildString`/`extractCanvas`。
3. **关键实证**:`ye.messageBus === window._MSG_BUS_`(全局总线)。`/PrjDB/*` 读类经它**直接可调**:
   `/PrjDB/pcb/getAllPrimaryKeys`→`["2623a85edf12f117"]`;`/PrjDB/schematic/getAllArrDatas`→sch 文档;
   `/PrjDB/sheet/getAllArrDatas`→sheet `f293bb407eb959c5`;`/PrjDB/pcb/getData [uuid]`→PCB 文档元数据。
4. **底层写签名(bundle 实证)**:`z(te.SHEET.SET_CANVAS, async(t,s,r)=>(await J(r).sheet.setCanvas(t,s)).success)`
   ⇒ `_MSG_BUS_.rpcCall("/PrjDB/sheet/setCanvas",[sheetUuid, canvasData, projectId?])`,
   `r` 缺省 `ye.currentProject.projectId`。同理 pcb/symbol/footprint/device 各有 setCanvas/createData/addData。

**坑(实证)**:页内 `awaitPromise` 等一个无回执的 rpc 会**冻结整条 CDP**(后续 evaluate 全 timeout,需整页 reload 复位)。
⇒ 必须 **fire-and-poll**:`.then` 写 `window.__rr`,再分轮询读。已固化进 `prjdb_lowlevel.py::rpc()`。
`getCanvas` 会委派活动 worker,未就绪时挂起 → 读图元优先用 `buildString`/`.epru` 格式或确保工程 ready。

**沉淀**:`prjdb_lowlevel.py`(非阻塞 rpc + topic 常量)、`_prjdb_topics.txt`、`_mgr_projectworker_topics.txt`、
`_epro_dump/`(.epru 格式样本)。**意义**:确定性建板的真正入口 = 构造图元 canvas 直接 `setCanvas` 灌入工程数据库,
不经 GUI、不经库后端、不经脆弱合成鼠标 —— 一次构造整张设计字典直接落库。反者道之动,从底层突破一切。

## ★★ 会话 2d 终局突破:确定性放件 = 真实输入自标定(根治非确定·已实证)

> 这是本会话最有价值的可达成果,直接根治了前几轮反复卡住的"合成鼠标放件非确定"瓶颈。

**链条**(全部实证):
1. 一切**渲染/视口耦合**的 EXTAPI(`convertDataOriginToCanvasOrigin` 返回恒等回显、
   `navigateToCoordinates`/`zoomTo*` 空桩、`importProjectByProjectFile`/`netlistComparison`/
   `getDsnFile` undefined、`create` 向库后端拉符号 hang)在本自动化 Chrome 上下文里**rpc 处理器未接通** → 不可用。
2. 但编辑器**状态栏实时显示光标处数据坐标**(X:/Y:),且**真实 OS 输入(computer 工具)会更新它,
   CDP 合成 `Input.dispatchMouseEvent` 不更新**(画布只认真输入)。状态栏同时写进 DOM → `evaluate` 直接读,免截图。
3. ⇒ **自标定**:真实鼠标移到 ≥3 个已知像素 → 读数据坐标 → 最小二乘解 **像素↔数据 仿射** →
   任意目标数据坐标算出像素 → computer 工具移/点 → **确定性放件**。

**实证标定**(243% 缩放·computer 1024×768 空间):`data_x=5.15·px_x−2000`;`data_y=−3.833·px_y+1020`。
验证:目标 `data(0,0)` → 预测像素 `(388,266)` → 实读 `X:0 Y:5`(误差几 data 单位,加点可细化)。
(x/y 比例不同 = 1024×768 到真实显示 ~16:9 非等比映射,仿射仍成立。)

**沉淀**:`vm_calibrate.py`(`read_status_xy`/`solve_affine`/`data_to_px`/`px_to_data`,自检通过)。
**用法**:视口固定后标定一次 → 批量算像素放件;**任何 pan/zoom 后必须重标定**。
**意义**:不依赖任何被挡住的渲染 rpc,用"真实输入 + 视觉/DOM 反馈闭环"拿到确定性 —— 反者道之动。

**两侧通用(已实证)**:同一机制在**原理图编辑器**也成立(实测:像素(400,350)→状态栏 X:5.1 Y:4.6 inch)。
⇒ 放件脆弱性真正所在的原理图侧同样可确定性放件;PCB 侧/原理图侧仅单位不同(inch vs 10mil),
标定与目标取同一单位即可。**确定性建板全链路(原理图按精确坐标放件→连线→同步PCB)由此打通。**

## 〇、★ EXTAPI 程序化可达性边界图谱(会话 2d 实测·关键资产)

> 反复实测得到的核心规律:**EXTAPI 分两类——"数据/生命周期"类程序化可达;"高阶向导/比对/导入"类是 UI 绑定,
> 经 CDP 程序化调用普遍返回 undefined/falsy(由 UI 驱动并把结果写进面板,不向调用方返回)。**
> 这张图谱本身就是用户要的"在实践中暴露的边界缺陷",直接决定下一轮该走哪条路。

| 方法 | 程序化结果 | 判定 |
|---|---|---|
| `dmt_Project.createProject` / `scaffold` | 返回 uuid,工程真建 | ✅ 可达 |
| `dmt_Project.getAllProjectsUuid(teamUuid,...)` | **需传 teamUuid**,否则返回 `[]`;传齐返回 90 | ✅ 可达(此前误判为退化) |
| `dmt_Folder.createFolder(name,teamUuid,...)` | 传齐 teamUuid 返回 folder uuid | ✅ 可达 |
| `dmt_Project.getProjectInfo` / `sys_FileManager.getProjectFileByProjectUuid` | 返回 info / `.epro2` File | ✅ 可达 |
| place/save/modify/importChanges(自动点 Apply)/export(Gerber/BOM/PNP) | 端到端产出真实可制造件 | ✅ 可达(但放件走合成鼠标,非确定) |
| `pcb_Net.getNetlist('JLCEDA')` | 返回 JSON 字符串(网表) | ✅ 可达 |
| `sch_Netlist.getNetlist('JLCEDA')` | 内部 footprint 显示查询 fire-and-forget → **hang** | ⚠️ 卡死(用 pcb 侧或 .enet 导出绕) |
| `sch/pcb_Net.setNetlist` | 返回 true 但**只设参考网表,不建器件/网络** | ❌ 非建网入口 |
| `sys_FileManager.importProjectByProjectFile(file,...,saveTo)` | in-page File + 有效 saveTo **仍 falsy**,无工程产生 | ❌ UI 绑定(后端拒收 client File) |
| File→Import→JLCEDA(Professional) UI 点击 | **既不触发 `<input type=file>` 也不触发 `showOpenFilePicker`**(已 monkeypatch 计数) | ⚠️ 需更精细驱动 |
| `sys_Tool.netlistComparison(nl1,nl2)` | 传 .enet JSON 串 → **返回 undefined** | ❌ UI 绑定(疑需特定网表文件格式/写面板) |
| `sys_Tool.schematicComparison` / `pcbComparison` | 函数体为空 `{}` | ❌ 空桩(未实现) |

**战略含义**:逆向工程的"导入成品 + 自动比对"两个高阶能力在**纯 CDP 程序化层被 UI 绑定挡住**。
要兑现逆向全链路,只剩两条真路:**(A)** 驱动真实 UI(computer 工具 / DAO Bridge browser_* / monkeypatch
`showOpenFilePicker` 喂 File 走完整 UI 管线);**(B)** 强化已验证的**正向程序化构建 + 导出**链
(根治放件非确定:接原生 `autoLayout`/`autoRouting`、或确定性坐标),用它产出参考件再做对比。

### 〇.1 引擎级 API 实测(会话 2d·布线/布局/创建)
反出并实测了一批引擎级方法,进一步印证上面的统一边界:
| 方法 | 语义/实测 | 判定 |
|---|---|---|
| `pcb_ManufactureData.getDsnFile(name)` | **实测在有件 PCB(3 件/4 线)上仍返回 undefined**;同一文档 `getGerberFile` 却返回 7268B File ⇒ **DSN 专属 UI 绑定**(疑绑自动布线交互流) | ❌ UI 绑定 |
| `pcb_Document.importAutoRouteSesFile(file)` | 回灌 FreeRouting **SES** 布线结果 | 待验(疑同 DSN 绑 UI) |
| `pcb_ManufactureData.getAutoRouteJsonFileForJRouter()` | **JLC 自带 JRouter 自动布线器**的输入 JSON;疑同 DSN 绑自动布线交互流 | ⚠️ 反出但疑 UI 绑定 |
| `pcb_ManufactureData.getGerberFile/getBomFile/getPickAndPlaceFile/getNetlistFile` | **制造类导出全部 ✅ 程序化可达**(Gerber 实测 7268B);**与"喂自动布线器"类(DSN/JRouter)形成鲜明对照** | ✅ 可达 |
| `pcb_Document.importAutoRouteJsonFile(file)` | 回灌 JRouter 布线结果 | 待验 |
| `sch_Document.autoLayout({netlist,designatorDeviceTypeMap})` | **只排布已存在器件**(传 uuids/netlist),实测对空图返回 `{}`、不新建器件 | ⚠️ 排布≠创建 |
| `sch_Document.autoRouting({...})` | 同上,自动连线(对已存在器件) | ⚠️ 需先有件 |
| `sch_PrimitiveComponent.create(t,i,n,r,s,a,o,l)` → `new fa("part",...)` | **唯一非鼠标创建原语**;`create("<deviceId>",x,y)` **实测 hang**(疑创建时向库后端拉取符号,headless CDP 不完成);仅 `t` 单参 → `数据不符合规范` | ❌/⚠️ 卡在库后端拉取 |
| `sch/pcb_PrimitiveComponent.placeComponentWithMouse/placeSymbolWithMouse` | 走合成鼠标(用已加载的库状态)——**当前唯一能真放件的路**,但非确定 | ⚠️ 鼠标依赖 |

**★ 统一根因(本会话最深结论)**:**凡需"经后端拉取/上传内容"的操作(导入工程、从库创建器件、网表比对、
器件库符号解析)在程序化 CDP 下一律 hang 或返回 falsy;只有"页内数据操作 + 生命周期 + 用已加载库状态的
鼠标 UI 放件"能成。** 这把此前散落的负结论(import falsy / comparison undefined / create hang)收敛成一条。
- ⇒ **下一跃迁的两条真路**:① 用 **DAO Bridge `browser_*`(含 browser_upload)** 在真实浏览器里走完整 UI
  导入/放件管线(后端上传通道完整);② 预加载库状态后再程序化 `create`(让符号已在内存,绕开后端拉取)。
- **更新(实测后修正)**:原以为 FreeRouting/JRouter 导出侧可立即兑现 —— **错**。`getDsnFile` 在有件 PCB
  上仍返回 undefined,而**同一文档 `getGerberFile` 正常出 7268B**。⇒ 边界更精确:**制造类导出
  (Gerber/BOM/PNP/Netlist)程序化可达;"喂自动布线器"类(DSN/JRouter/SES)绑自动布线 UI 交互流,程序化拿不到。**
  ⇒ 接 FreeRouting/JRouter 也必须走真实 UI(DAO Bridge `browser_*`)或在自动布线对话框内触发。

## 一、当前稳定可复现的能力(全链路核心环)

每次运行 `build_blinker.py` 都**端到端走通并产出真实可制造文件**:

```
scaffold(建工程/原理图/PCB) → open sch → place(放件) → save
  → sync_to_pcb(importChanges + 自动点 Apply Changes) → 封装落 PCB
  → board_outline(自动算 bbox + 画 L11 板框) → save → DRC
  → export: Gerber(含 GKO 等 9 层) + BOM.xlsx + PNP + Netlist
```

可制造产物在 `exports/Dao_Blinker_<ts>/`,Gerber/BOM/PNP/Netlist 均有效。
**结论:工程生命周期 + PCB 侧 + 导出链路是稳的。**

## 二、本轮实测发现的真实边界(原理图侧合成鼠标操作)

根因一句话:**`placeComponentWithMouse` / `sch_PrimitiveWire.create` 走的是
"合成鼠标像素坐标 → 画布视口(缩放/平移)→ 图纸数据坐标"这条链,而视口状态
在自动化里是非确定的**,于是连锁出三类坑:

1. **放件落到图纸外**:像素 730 在某视口下映射到数据 x≈1510,**越出 A4 图纸右缘
   (~1170 单位)**。落在图纸外的件 save 后不持久 / 连到该脚的导线 `create failed`。
2. **丢件**:同一轮放 4 件,save 后偶发只剩 3 件(最初怀疑"相同器件去重",但换成
   不同阻值的 R1/R2 仍丢 → **是位置/时序相关的非确定性,不是器件去重**)。
3. **导线 create failed**:即便两脚都在图纸内,`sch_PrimitiveWire.create` 仍会失败;
   且经过几十次建工程/reload 后,编辑器实例**退化**——`getAllPrimitiveId` 只有在
   原理图为**当前激活渲染文档**时才成功(切到 PCB 文档后即报"获取所有器件的图元ID失败")。

### 已确认走不通 / 半成品的 API(避免下轮重复踩)
- `sch_Document.navigateToCoordinates(t,i)` → 实现是 `return !1`(**空桩,恒 false**),
  无法用它把视口居中到指定数据坐标再放件。
- `sch_PrimitiveComponent.create(t,i,n,r,s,a,o,l)`(`new fa("part",...)`):8 参,
  各种排列组合都报「数据不符合规范」,**schema 未反出**(下一步重点)。
- `sch_PrimitiveComponent.modify(t,i)`:**支持 `{x,y,rotation,mirror,designator,...}`**,
  本是确定性"放后归位"的理想解;但其末尾 `(await Yf([I]))[0]` 的命令确认在本自动化
  上下文里拿到 `undefined` → 报 `Cannot destructure property 'cmdKey' of 'i'`。
  即**已落盘、已在册、activateDocument 后仍失败** → 命令栈在 headless/CDP 下不回执。
  ⇒ `set_part()` 因此一直是 best-effort 静默失败,**位号实为 EDA 自动分配**,非我们写入。

### 已确认存在、值得下轮接入的"引擎级"API(反者道之动:别再手搓)
- `sch_Document.autoLayout({uuids, netlist, designatorDeviceTypeMap})` — 原生自动布局
- `sch_Document.autoRouting({uuids, netlist, designatorDeviceTypeMap})` — 原生自动布线
- `dmt_EditorControl.zoomToAllPrimitives / zoomTo / zoomToRegion / zoomToSelectedPrimitives` — 规范化视口
- `dmt_EditorControl.activateDocument / getCurrentRenderedAreaImage` — 激活文档 / 取渲染图

## 三、下一步根治路线(按性价比排序)

1. **视口标定放件(最高性价比)**:放件前先 `zoomToAllPrimitives`/`zoomTo` 把视口
   归一到已知区域;放第一件后读其落盘数据坐标,**反算"像素→数据"仿射变换**
   (两点定标:斜率+偏移),据此把后续件放到指定 on-sheet 数据坐标。彻底消除"落图纸外"。
2. **反出 `sch_PrimitiveComponent.create` 的 schema**:用 `Debugger.getScriptSource` /
   断点抓 `fa` 构造器对参数的校验,得到确定性放件(无鼠标、无视口依赖)——最干净的根。
3. **接 `autoLayout` + `autoRouting`**:放件 + 建网后,直接交给原生引擎布局布线,
   既稳又是"继承成熟工具"的方向(对齐用户"自动布线模块"的诉求)。
4. **修 `modify` 的命令回执**:研究 `Yf` 期望的命令结果结构 / 是否需 `commitCommand`,
   打通后 `modify` 即可做确定性归位与位号写入。
5. **编辑器退化治理**:每条全链路结束/切文档后,确保原理图为激活渲染文档;
   必要时存盘安全 reload 重置实例,避免几十次循环后的状态退化。

## 四、本轮代码沉淀(安全、非破坏性,已保留)
- `eda_flow.part_pins()`:`get(pid)` 预热 + 多轮重试,缓解"刚放件取脚失败"。
- `eda_flow._pin_xy()` / `net_route()`:按引脚号取坐标 / 每网专属竖直 lane 汇接
  (lane 必须夹在图纸内,否则同样 `wire create failed`——已在注释标注)。
- `build_blinker.py`:全程**故障软化**——放件/连线失败不再中断,以"落盘实到件"为准
  继续走完同步/板框/DRC/导出,保证链路恒可跑通并产出可制造件。

## 五、反者道之动 · 反向工程路线(本轮新挖,绕开正向放件瓶颈)

> 用户指向:拿市面成熟成品板,从成品**逆推**回本源设计(选型→网表→布局→布线),
> 在逆推实践中暴露并修复系统缺陷。反向恰好绕开"合成鼠标正向放件"的脆弱瓶颈。

### 已摸清的反向 API 面(EXTAPI 实测)
- **`sch_Netlist.getNetlist(type)` / `setNetlist(type, netlist)`** 与
  **`pcb_Net.getNetlist(type)` / `setNetlist(type, netlist)`**:网表**读/写**。
  `setNetlist` 即"由网表确定性构建设计",**无需鼠标、无视口依赖** → 正是放件根治的反向解。
  PCB 侧支持多格式:JLCEDA/EasyEDA(`enet`)、PADS(`asc`)、Protel2(`net`)、
  Allegro(`tel`)、DISA(`dnet`)→ 可直接吃工业界真实板的网表。
- **`sys_Tool.netlistComparison(nl1, nl2)`**:网表比对 = 逆推"与参考比对"的核心原语。
- **`pcb_Document.importAutoRouteSesFile(file)`** + `importAutoRouteJsonFile` /
  `importAutoLayoutJsonFile`:导入 **Specctra SES** / 自动布局结果 →
  可接 **FreeRouting**(成熟开源自动布线器,输出 SES)等外部引擎(对齐"继承成熟工具")。
- **`sys_FileManager.importProjectByProjectFile(file, "JLCEDA Pro", {associateFootprint,associate3DModel,...})`**:
  整工程导入(可关联封装/3D)。
- **`pcb_ManufactureData.getAltiumDesignerFile()`** + `sys_FormatConversion.convertAltiumDesignerLibraries...`:
  Altium 往返 → 逆推 Altium 设计。
- 原生引擎:`sch_Document.autoLayout({uuids,netlist,...})` / `autoRouting(...)`。

### 实测到的 JLCEDA 规范网表数据模型(已存样本 `demos/pcb_netlist.json`)
```
{ version, components:[ {                       # 每个器件
      attributes:{ Designator, Name, Device, FootprintName, DeviceName,
                   "3D Model", Supplier, "Add into BOM", "Convert to PCB", ... },
      pinInfoMap:{ "<pinNo>": { name, number, net } }   # 网络挂在每个引脚的 net 字段
  } ], designRule, netClass, equalLengthNetGroup, differentialPair }
```
即:**网络 = 各器件 pinInfoMap[n].net 的同名归并**;BOM/封装/3D 全在 attributes 里。
⇒ 逆推一块板 = 还原出这份结构 → `setNetlist` 灌入 → 即得可编辑设计。

### 本轮反向实测发现的坑
- **`sch_Netlist.getNetlist` 会 hang**:其内部 `await /PrjDB/footprint/getDisplay...`
  在本 CDP/headless 上下文不 resolve(与 openDocument 同类的 fire-and-forget 病)→
  CDP 传输超时。**对策:走 `pcb_Net.getNetlist`(不含封装显示名 loop,快且稳)**,
  或给 sch 侧那条内部 rpc 加 fire-and-forget+轮询。
- 重型调用(网表/导入)需放大 CDP 传输超时(`call(..., timeout=40~120)`)。

### setNetlist 往返实测(本轮·已查清真实 schema 与语义)
- `pcb_Net.getNetlist('JLCEDA')` **原生返回一个 JSON 字符串**(非对象);`JSON.parse` 后:
  ```
  { version, components:{ "<UniqueID>": { props:{...BOM/封装...}, pinInfoMap:{ "<pin>":{name,number,net} } }, ... },
    designRule, netClass, equalLengthNetGroup, differentialPair }
  ```
  注意:器件容器是**以 Unique ID 为键的对象**;器件字段是 **`props`(不是 `attributes`)** + `pinInfoMap`。
  (此前 Python 侧 Designator=None 即因错读 `attributes`;且 CDP returnByValue 偶发多层字符串化,
  **正解:整段 get→改→set 在浏览器内 evaluate 完成,native 对象不过 CDP 序列化**。)
- **关键语义发现**:在浏览器内把两个器件 `pinInfoMap[1].net` 同赋 `DAO_TESTNET` →
  `pcb_Net.setNetlist('JLCEDA', JSON.stringify(nl))` **返回 `true`**,但回读网表**查无该网名**。
  ⇒ 推断 `pcb_Net.setNetlist` 设的是**参考/期望网表(供 DRC 与 `netlistComparison` 比对)**,
  **并非 PCB 实际铜层网络拓扑**;实际网络拓扑来自**原理图**经 importChanges 下传。
- ⇒ **确定性建网的真正入口是 `sch_Netlist.setNetlist`(构建原理图)+ `sch_Document.importChanges`**;
  pcb 侧 set 仅用于"灌入参考网表做反向比对"——这恰好是**逆向工程比对**的利器(用成品网表当参考)。

### ★ 关键判决:setNetlist 不建器件(实测·确定性结论)
- 把含真实器件 props 的 .enet 网表(`exports/Dao_Blinker_092358/...enet`)灌进**全新空原理图**:
  `sch_Netlist.setNetlist('JLCEDA', enetJSON)` 返回 ok 但 **`ret` 为 undefined,`parts()` 仍为空**。
  ⇒ **`setNetlist`(sch 与 pcb 皆然)只设"参考网表",不创建任何器件/符号/网络。**
- 全 EXTAPI 扫描"能创建设计内容的导入"方法,仅 **`sys_FileManager.importProjectByProjectFile`**
  一个真入口(+ `sch/pcb_Document.importChanges` 做 sch↔pcb 同步;`importAutoRoute*` 仅回灌布线)。
- **统一结论(反者道之动落到实处)**:**确定性建网 = 导入成品工程文件**(而非 setNetlist、也非鼠标放件)。
  这把"确定性建网"与"逆向工程"两条路**合一**:不再手搓放件,直接 `importProjectByProjectFile`
  灌入真实成品(EasyEDA/LCEDA/Altium/KiCad/EAGLE…)→ 得可编辑器件+网络 → 再逆推/比对/布线。
- `.enet` 网表规范格式(已存样本):
  ```
  { version:"2.0.0",
    components:{ "<UniqueID>":{ props:{ Footprint, Device, Designator, FootprintName,
                                        DeviceName, "3D Model", Supplier, "Convert to PCB", ... },
                                pinInfoMap:{ "<pin>":{name,number,net} } } },
    designRule:{trackPhysics,netRule}, netClass, equalLengthNetGroup, differentialPair }
  ```
  网络 = 各 pin 的 `net` 同名归并;器件身份全在 `props`(Device/Footprint 为库 uuid)。

### 导入入口已解剖(签名 + 文件形态 + 实测)
- **`sys_FileManager.getProjectFileByProjectUuid(uuid)`** 返回一个 **`File`(.epro2,zip,实测 51653B)**
  —— 即"成品工程文件"。`getProjectFile`/`getDocumentFile`/`getDocumentSource` 同族。
- **`importProjectByProjectFile(file, format="JLCEDA Pro", options, r, s)`** 全签名:
  ```
  options = { importOption:"ImportDocument", viaSolderMaskExpansion:"cover",
              boardOutlineSource:"keepout", schematicObjectStyle:"system",
              associateFootprint:true, associate3DModel:true, importFootprintNotesLayer:true }
  ```
  format 形参可换别的源(Altium/KiCad/EAGLE…,具体枚举待逐一试)。
- **逆向比对原语**(比 netlist 更直接):`sys_Tool.schematicComparison` / `pcbComparison` / `netlistComparison`。

### ★ 导入网关已确认全格式(File→Import 菜单实拍)
LCEDA Pro 的 **File→Import** 支持几乎全部工业格式,**逆向工程标的可直接喂入**:
`DXF`、`Image`、`JLCEDA(Standard)`、`JLCEDA(Professional)`、**`Altium Designer`**、
**`Allegro/OrCAD`**、**`EAGLE`**、**`KiCad`**、**`PADS/PADS Pro`**、`Protel`、`LTspice`、`T/DISA 4001`。
⇒ 反向方向(拿成品板逆推)在工具层**完全被支持**:Altium/KiCad/EAGLE/Allegro/PADS/Protel 工程都能进。
- 程序化 `importProjectByProjectFile` 已完整反出实现:
  ```
  let a = await rpcCall("extensionApi.SYS_FileManager.importProjectByProjectFile",
            {projectFile:t, fileType:i, props:n, saveTo:r, librariesImportSetting:s});
  if(a) return await rpcCall("DMT_Project.getProjectInfo", a);   // a=新工程 uuid
  ```
  即 `r=saveTo`(目标文件夹/位置)、`s=librariesImportSetting`。
- **★ 重大修正(此前误判)**:之前以为编辑器退化(`getAllProjectsUuid` 恒 0)——**错**。
  反出实现:`getAllProjectsUuid(teamUuid, folderUuid, workspaceUuid)`,**不传 teamUuid 直接返回 `[]`**。
  传 `teamUuid='5bd8145e…'(Personal)` → **返回 90 个真实工程**。编辑器一直健康。
  同理 `createFolder(name, teamUuid, parentFolderUuid)`、`createProject(friendlyName,name,teamUuid,folderUuid,...)` 都需 teamUuid;
  传齐后 `createFolder` 正常返回 folder uuid。
- **实测穷尽(确定结论)**:`file`(in-page,从 getProjectFileByProjectUuid,未过 CDP)+ `saveTo`=有效 folder uuid
  调用 `importProjectByProjectFile` → rpc **仍恒返回 falsy**(folder 内查无新工程)。
  ⇒ **`saveTo` 不是症结;`importProjectByProjectFile` 的后端 rpc 在程序化调用下不生效**
  (疑 projectFile 需经真实上传通道 / user-gesture 来源的 File,client 重建的 File 后端拒收)。
- **UI Import 也实测**:File→Import→JLCEDA(Professional) 点击后 **既不触发 `<input type=file>` 也不触发
  `showOpenFilePicker`**(已 monkeypatch 计数,fsapi=0 input=0)——该项可能先弹应用内模态再选文件,或需更精细驱动。
- ⇒ **可达的逆向工程不必卡在导入**:账号内已有 **90 个真实工程**,可直接 `打开→取网表(.enet)→
  schematic/pcb/netlistComparison 比对→分析设计`,这条**完全程序化可达**,先用它跑通逆向比对闭环。

### 反向路线下一步(可执行顺序)
1. **用账号内 90 个真实工程跑通逆向比对闭环**(无需导入):打开工程→取 .enet 网表→
   `schematic/pcb/netlistComparison` 两工程逐层比对→暴露差异。**完全程序化可达,优先做。**
2. **导入真实外部板**(KiCad/Altium):程序化 rpc 不生效,留两条路——
   (a) 更精细驱动 UI Import(可能先弹应用内模态);(b) monkeypatch `showOpenFilePicker` 返回我方 File
   绕过原生选择器、走完整 UI 导入管线。
2. 取一块真实开源硬件板(公开 Gerber/网表/BOM)→ `importProjectByProjectFile` 或
   网表导入 → 还原可编辑设计。
3. **FreeRouting 闭环**:导出 Specctra DSN → FreeRouting 跑线 → `importAutoRouteSesFile` 回灌。
4. `netlistComparison` 做"成品 vs 我方还原"的逐层一致性校验,暴露差距、逐项修。

*为学者日益,闻道者日损。损之又损,以至于无为。先把边界看清,再以最小动作根治。*

---

## ★★★★★ 会话 2g 终局:整板**底层克隆**打通(弃 EXTAPI / 弃 GUI · 道并行而不相悖)

承接两路并归一为**整板低层克隆**靶子,一举证成:
① 突破 JLC 原生 API 上限(二次逆流·整板写入);② 从**成品板反向推演**并确定性重建。

### 决定性结论:官方导入 API 是死路,worker `import` 才是底层正道
- `extensionApiMessageBus2 = window.top._MSG_BUS2_EXTAPI_`。直驱裸总线复测
  `SYS_FileManager.importProjectByProjectFile`(传页内自建 File)→ **resolve `{}`(无错无果)**。
  根因:**该桥按 JSON 序列化入参,`File`/二进制 → `{}`**(过桥即丢)。⇒ 官方导入 API 天花板坐实。
- 同理 `dmt_Project.createProject(...)` 多参直驱亦静默返回空(扩展权限门控)。
  但**经 `eda_api.call("dmt_Project.createProject", name)` 单参走既有封装可正常建工程**(实测得 uuid)。

### 逆出 worker 端**整板导入**端点(走 worker 总线,非 JSON 桥,二进制不丢)
```
project-worker.js:
  workerBus.rpcService(public.import, t => instance.import(t))
  import(s){ messageBus.publish("startBatch",uuid); new Xd(s,this).start() }   # Xd=ImportTarget
  Xd{constructor:{uuid,datas,structure}}.start():
     structure==="export3.0" || typeof datas.dataStr==="string"
        → parseExport3_0(datas): Mn({str:dataStr}) 解析 .epru → gc({...,datas}) 逐 entity 写工程库
     structure==="export2.0" || datas.config?.defaultSheet!==undefined → parseExport2_0
     structure==="exist3.0"  || datas                                  → importTarget
```
⇒ **топic `/mgr/projectWorker/import`,入参 `{uuid:<目标工程>, datas:{dataStr:<.epru 全文>,images:{}}, structure:"export3.0"}`**。
封装见 `canvas_lowlevel.import_project()`;端到端复现见 `demo_project_clone.py`。

### 端到端实证(NE555 Blinker 成品板 → 全新空工程)
1. `getProjectFileByProjectUuid` 取成品 .epro2 → 解包 .epru(211,100 B,20 子文档)。
2. `createProject` 建空工程 `DAO_BOTTOM_CLONE_*`;打开默认页使 worker 实例化。
3. `wrpc('/mgr/projectWorker/import', {uuid, datas:{dataStr}, structure:"export3.0"})`
   → `{success:true, result:{map:{symbolMap×5, deviceMap×5, footprintMap×3, schematicMap×1, pcbMap, pathMap}}}`
   (整板逐 entity 落库 + 新旧 uuid 自动重映射)。
4. `sch_Document.save` → **服务器回读** .epro2 解包:
   `FOOTPRINT×3 / SYMBOL×5 / DEVICE×6 / SCH×2 / SCH_PAGE×2 / PCB×2 / PANEL×2 …`
   导入页 `SCH_PAGE{COMPONENT×3, ATTR×68}`;导入 `PCB{PRIMITIVE×37, COMPONENT×2, PAD_NET×10, NET, LAYER×60, LINE×4}`。
5. **编辑器可视化完好**(proofs/clone_ne555_rendered.png):`Fit Selection` 框出
   **U1=NE555 八脚符号(GND/TRIG/OUT/RESET + VCC/DISCH/THRES/CONT,脚号 1-8)+ R1 电阻**,
   符号几何 / 引脚 / 位号全渲染 = **渲染完整无缺**。proofs/clone_project_tree.png 见工程树
   Board1_1 / Schematic1_1 / PCB1_1 整套导入。

### 道:为何这条成立而 EXTAPI 不成立
worker 总线(BroadcastChannel)承载结构化字符串无损;`.epru` 即 dataStr,过 worker 不经 JSON-File 丢失。
**反者道之动**——从成品(.epru)反向一次性灌库,比"逐元素合成"更确定、更高效;无为(不放一颗件)而无不为(整板自现)。

---

## ★★★★★★ 会话 2h:与**社区底层融为一体** —— 拉取并逆向社区超复杂成品

用户升维:嘉立创本身是巨大资源库(立创开源广场 oshwhub.com),应整合社区一切底层资源,
从大佬的超复杂成品逐层反向推演。本会话把社区与我方底层管线打通并实证。

### 社区资源底层路径(逆向所得)
- 开源广场在 **oshwhub.com**(Next.js,与 pro.lceda.cn 跨域;直 fetch 被 CORS 挡)。
  ⇒ 经浏览器在 oshwhub **同源**调其私有 API:
    `GET /api/project/{uuid}`            工程元数据(title/attachments/origin/members…)
    `GET /api/project/{uuid}/documents`  文档信息
    页面「在编辑器中打开」锚点 = `https://pro.lceda.cn/editor#id=<oshwhubUuid>,tab=*<docUuid>`
- ★ **关键突破:`sys_FileManager.getProjectFileByProjectUuid(<oshwhubUuid>)` 对“非我所有”的
  社区开源工程**直接返回完整 `.epro2`**(公有工程不受所有权门控)。
  ⇒ 任意社区成品的全部设计数据(原理图/PCB/器件/网表/层叠)皆可底层取回。
- 在 Pro 编辑器中打开社区工程须 **整页 reload**(仅改 location.hash 不会切换工程,SPA 不重载)。

### 实证:逆向「【全网首发】X86电脑主板」(oshwhub b77840665e2e48148c1b04ce84b5f7e7)
立创开源广场 11.6w 浏览 / 822 赞,作者 liuxiaotao。取回 `.epro2` = **22.4 MB**(.epru 解包 **177 MB**)。
`reverse_analyze.py` 反读出完整设计情报:
```
子文档: FOOTPRINT×1535 SYMBOL×203 DEVICE×200 SCH×1 SCH_PAGE×36 PCB×1 BOARD×1
PCB:    器件×1066  命名网络×1644  焊盘×17506  过孔×4554  走线×2780  物理层栈记录×17
网络分类: USB×111 power×61 display/HDMI/VGA×56 DDR/memory×47 PCIe×44 clock×31 ground×6
功能块(partId): CPU×16 PCH/南桥×14 DDR×8 USB×3 SATA×2 HDMI×1
位号: C×814 R×782 U×248 Q×142 … (真·PC 主板 BOM)
封装: R0402×390 C0402×287 C0603×207 …
```
⇒ 从一块成品 `.epro2`,**反读出**层叠/网络拓扑/电源树/高速总线(DDR/PCIe/USB/HDMI/VGA)/
   功能分区/BOM —— "反者道之动",不臆造,从落库记录里复现设计者全部意图。

### NET/记录真实 schema(逆向修正,前会话猜测有误)
- **NET 名在 `head.id` = `["NET","<name>"]`**,不在 payload(payload 只有 netType/differentialName…)。
- COMPONENT.payload: `{partId, x, y, rotation, isMirror, attrs}`;位号/封装在 **ATTR**(key=Designator/Footprint)。
- DOCHEAD **无 name/title**(只有 docType/uuid/version/user);文档名存服务端结构,离线不可得。
- `project2.json`(zip 内)= 工程元数据(title/introduction/tags),非文档结构。

### 暴露的系统边界(待逐项突破)
1. **超大工程灌库**:177 MB .epru 经单次 worker import 透传风险高(浏览器/worker 内存、CDP 帧)。
   → 边界:大工程克隆需分文档/分段流式注入,或走服务端 copyProject(`/api/client/copyProject` 仅桌面端)/
     "Save Project to Cloud" 命令(SaveAs-Remote)在线复制,免数据透传。
2. 文档功能名离线缺失 → 功能分区现靠 net/partId 启发式;后续可经在线结构 API 取真实页名。

### 实证②:社区成品 → 我账号 **端到端克隆**(EDA-Pager 寻呼机)
oshwhub `d6f7528f939246efa27ed7e0ba022c6f`(立创课程案例,3.1 MB .epro2 / 10.6 MB .epru)。
**关键澄清**:.epru 是工程的完整编辑历史字典,含历史删除文档(段内带
`DELETE_DOC{isDelete:true}`)。该工程**全量** DOCHEAD = FOOTPRINT×55 SYMBOL×88 DEVICE×77
BOARD×4 SCH×4 PCB×4,但其中 **活动(未删除)只有** FOOTPRINT×50 SYMBOL×87 DEVICE×76
**BOARD×1 SCH×1 PCB×1**——即编辑器中实际可见的就 1 块活动板(其余 3 板系历史删除)。
经 `demo_project_clone.py`(getProjectFileByProjectUuid → createProject → worker
`/mgr/projectWorker/import`)克隆进我账号工程 `85732e77534b4392b67f4bc4507ad532`:
- import 映射:symbolMap×87 deviceMap×76 footprintMap×50 schematicMap×1 pcbMap×1 boardMap×1
  —— **与源活动结构精确一致**(1 板 1 SCH 1 PCB + 全部库实体)。
- 克隆 PCB **整板渲染完好**(见 proofs/pager_community_clone_pcb.png):板框 / 底层铜皮 /
  布线 / 过孔 / 焊盘 / ANTENNA 丝印 / 金手指;选中一条 TRACK 属性真实:
  Layer=Bottom, Length=51.939mm, **Net=+3.9V**, NetLength=72.363mm —— 网络/布线无损落库。

### ★ 本会话系统边界(逐项 · 含一处自我订正)
0. **【订正】先前误判的"多 Board 丢失"不成立**:我最初用全量 DOCHEAD 计数(`doc_counts`)
   把 3 块**历史删除板**误计为活动板,得出"4 板只克隆 1 板"的错误结论。深挖 .epru 的
   `DELETE_DOC` 标记后确认:源**活动结构本就只有 1 板**,worker import **如实克隆了全部活动设计**,
   无任何丢失。已修 `doc_counts(live_only=True)` 区分活动/历史删除,完整性判定改为逐类
   克隆 ≥ 源活动数。教训:.epru 是编辑历史字典,统计工程结构必须先按 DELETE_DOC 过滤。
1. **createProject 自带 1 块空默认板 → 已突破(精确克隆)**:克隆工程一度比源活动结构多 1 块空
   BOARD/SCH/PCB。**先证伪一条歧路**:EXTAPI `dmt_Board.deleteBoard(uuid)` 在 Web 仅改编辑器
   内存模型、**不持久化到服务端**(删除后 sch/pcb save + 等待,服务端回读仍为 2 板)。
   **再逆出 worker 端持久化删除端点**(与 import 同处写工程库,入参均为裸 uuid 字符串):
   - `/mgr/projectWorker/board/delete`(删板,不级联)
   - `/mgr/projectWorker/schematic/delete` / `/mgr/projectWorker/pcb/delete` / `/mgr/projectWorker/sheet/delete`
   实证:删空默认板 + 级联删其 SCH/PCB/SCH_PAGE → 服务端回读 **BOARD/SCH/SCH_PAGE/PCB 各 ×1,
   与源活动结构精确相等**(`精确克隆: True`)。已沉淀为 `prune_to_imported()`(按 import boardMap
   保留被克隆板、删其余)。残留极小:DEVICE 比源多 1(createProject 模板器件,库级非结构)。
2. **超大工程透传上限**:177 MB .epru(X86 主板)单帧 worker import 风险高(浏览器/worker
   内存 + CDP 帧)。→ 突破方向:分文档流式注入,或服务端复制(SaveAs-to-Cloud 命令)免透传。
3. **EXTAPI `copyProject` 在 Web 为空壳**(`copyProject(t,i,n,r,s){}` 空体);桌面端 copyProject
   走文件 path。→ 坐实:工程级复制在 Web 仍须走 worker 总线(非 EXTAPI),与既有"EXTAPI 天花板"一致。
4. **真·多活动板场景 → 已实测确认(单帧 import 全量重建多板)**:EDA-Pager 仅 1 活动板,
   故造一个**真·多活动板**靶子验证——对一个空工程**连续 import 两次** EDA-Pager,
   各自新建一块板 → 得 3 活动板工程(2 populated + 默认)。再**单次 import** 该 3 板工程克隆:
   `boardMap` **回 3 条映射**(三块活动板一次性全建),pre-prune BOARD×4(+createProject 默认),
   `prune_to_imported` 删默认后 **BOARD/SCH/SCH_PAGE/PCB 各 ×3,与源精确相等**。
   → **结论:单次 worker import 完整重建多活动板源的全部板**;先前"单 import 只 1 板"纯因
   EDA-Pager 源仅 1 活动板,并非 import 限制。多板能力(import + topology + prune)全链路打通。

### 沉淀的可复用资产
- `reverse_analyze.py`:成品 .epro2 → 设计情报(层叠/网络分类/功能块/BOM/封装)+
  `board_topology()` 多板装配拓扑(子文档 META 反向引用,区分活动/历史删除)。
- `demo_project_clone.py`:对**任意社区 uuid**端到端克隆(已验证非自有公开工程);
  含 `prune_to_imported()` **精确克隆**(worker 持久化删冗余结构)+ `doc_counts(live_only)`。
- **worker 持久化结构删除端点**(本会话逆出,裸 uuid 字符串入参,与 import 同写工程库):
  `/mgr/projectWorker/{board,schematic,pcb,sheet}/delete`、`device/delete`;
  对照:EXTAPI `dmt_Board.deleteBoard` 在 Web 仅内存、不落库。
- 社区接入要点:oshwhub 同源 `/api/project/{uuid}` 取元数据;
  `getProjectFileByProjectUuid(<oshwhubUuid>)` 取整包 .epro2(公开工程不受所有权门控)。

### 实证③:天下资源整合面(三大支柱·全程零 GUI 实测)
道法自然·取之尽锱铢——不从零搭建,把 JLC 已有的全球级资源逆出底层直接拿来用。一次扫描即编目
出可程序化复用的端点族(沉淀为 `resource_registry.py`,verified 项均本会话实测):

1. **天下器件库(LCSC/JLC 数百万元件,免自建库)**:`lib_Device.search("AMS1117-3.3")` 实测回
   10 条(首 = AMS1117-3.3_C6186);`lib_Device.getByLcscIds(["C6186"])` 按 LCSC 编号直取器件
   (uuid 解析成功)。配 `lib_Footprint/Symbol/3DModel.search` 与 `registerExtendLibrary`。

2. **跨生态格式整合(KiCad/Altium/外部布线器 → JLC)**:`sys_FormatConversion`(Altium 库转换)、
   `pcb_Document.importAutoRouteSesFile`(吃 FreeRouting `.ses`)、`importAutoLayoutJsonFile`、
   worker `/import`(.epru 整板无损灌库,正道)。

3. **全链路制造闭环(程序化导出 + 比对)**:在一块 populated 克隆上实测——`pcb_Net.getNetlist`
   回 JSON 网表(version/components/designRule);`pcb_ManufactureData.getNetlistFile`→`Net_List.enet`
   (732B)、`getBomFile`→`Export_BOM.xlsx`(6.6KB)、`getGerberFile`→`Gerber_*.zip`(4.3KB);
   `sch_ManufactureData.getNetlistFile`→`.enet`(979B)。`sys_Tool.netlistComparison` 备网表比对。

→ 三支柱 + 既有社区接入/精确克隆,构成"任何需求 → 匹配已集成能力"的资源底座(`resource_registry.print_registry()` 可一览;`search_devices/devices_by_lcsc/export_file/get_community_epro2` 为薄封装)。

### .epru 文档关系·实测 schema(深挖订正)
拆解源 .epru 各子文档段,纠正先前"拓扑不在离线包"的猜测——**父子拓扑其实就在子文档 META 里**:
- **BOARD** 段:`META{"title":"Board1","zIndex":1}`(板标题/层序)。
- **SCH** 段:`META{"title":"Schematic1","board":"<boardUuid>",...}` —— SCH **反向引用其 BOARD**。
- **SCH_PAGE** 段:`META{"title":"P1","schematic":"<schUuid>",...}` —— 页**反向引用其 SCH**。
- **PCB** 段:`META{"title":"PCB1","board":"<boardUuid>",...}` —— PCB **反向引用其 BOARD**。
- 段首 `DELETE_DOC{isDelete:true}` 标记该文档为历史删除。
即:**离线 .epru 自含完整多板拓扑**(经子文档 META 的 board/schematic 反向引用),
可据此对**多活动板**工程做按板分组/逐块迁移。这为未来"真·多活动板克隆"提供了离线可解析的拓扑依据。

### 实证④:全链路「源 ↔ 克隆」无损比对(制造数据级,全程零 GUI)
不止结构层 `doc_counts` 相等,沿制造全链路逐层取证——对**社区成品源**(EDA-Pager
`d6f7528f939246efa27ed7e0ba022c6f`)与其**底层克隆**(worker `/import`)各自在编辑器
中打开 PCB、程序化导出制造四件套并解析语义计数比对(`demo_fullchain_compare.py`):

| 制造产物 | 源 | 克隆 | 结论 |
|---|---|---|---|
| 网表 `.enet` | nets=50, 122738B | nets=50, 122738B | **uuid 规范化后逐字节相同(残余差异 0 行)** |
| BOM `.xlsx` | 行=33, 位号=92 | 行=33, 位号=92 | 一致 |
| Gerber `.zip` | 14 文件(GTL/GBL/GTS/GBS/GTO/GBO/GTP/GKO/GDL/DRL×3/json) | 14 文件 同层集 | 一致 |
| Specctra `.dsn` | 153365B | 153367B | 一致(±2B 时间戳) |

**关键发现(诚实定性)**:源↔克隆网表的字节差异**仅来自 import 对库 uuid 的重映射**
(footprint/device 内部 ID,如 `8bf562b0…_…`→`f53c4301…_…`),而 Designator(U1…)、
BOM 归属、3D 模型、网络拓扑**全等**。把所有 hex uuid 令牌按首现顺序规范化为 `#N` 后,
两份 `.enet` **逐字节相同(0 差异行)** → 克隆在制造数据层**语义无损**,差异是必然且
无害的命名空间重编号。`netlist_semantic_identical()` 固化此判定。

→ 至此「社区成品 → 底层克隆 → 制造产出」全链路**经数据级实证为无损**:用户拿任意大佬
成品,我方既能精确克隆其活动结构,导出的网表/BOM/Gerber 亦与源语义一致,可直接投产。
