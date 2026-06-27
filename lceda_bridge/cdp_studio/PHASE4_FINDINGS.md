# Phase 4 · 本体测绘与实战发现录(道法自然 · 万物并作吾以观复)

> 本文沉淀 Phase 4「嘉立创EDA 本体接入」过程中**经实测验证**的底层结构与坑,供后续 Agent 直接承接。

## 一、本源结论:嘉立创EDA Pro Web 是**两层**,道并行而不相悖

| 层 | 载体 | 职责 | 绑定模块 |
|---|---|---|---|
| **账号层** | 同源 REST `https://pro.lceda.cn/api/*`(带登录 cookie) | 工程/文件夹/团队/用户的**生命周期 CRUD**(列表、新建…) | `eda_rest.py` |
| **编辑器层** | `window._EXTAPI_ROOT_`(经 Chrome CDP 在主页面调用) | **已打开**工程/文档内的原理图、PCB、图元、渲染等操作 | `eda_api.py` |

**关键澄清**:`_EXTAPI_ROOT_.dmt_Project.createProject(...)` 在编辑器页上下文是**空操作**(返回 `undefined/null`,不发任何网络请求);`dmt_Project.getAllProjectsUuid()` 只反映**当前已打开**的工程(无工程打开时恒为 `[]`)。
→ 账号级工程的"增/查"必须走 REST 层,**不能**指望 extapi 的 `dmt_Project.*`。二者互补,不可混淆。

## 二、最大的坑:Service Worker 拦截挂起所有运行时 fetch(已修复)

**症状**:GUI「新建工程 → 保存」弹 `Network Error!`;浏览器内 `fetch('/')`、`fetch('/api/...')` 永不返回(既不 resolve 也不 reject);CDP `awaitPromise` 超时。
**而**:shell `curl https://pro.lceda.cn/api/v4/projects/add` → HTTP 200;Python+cookie 直连 `/api/projects` → 正常。
**根因**:编辑器页注册的 Service Worker(scope `https://pro.lceda.cn/`)在本 VM 上拦截 fetch 后挂起,**只坏浏览器内请求,不坏 VM 网络**。读 API(getUserInfo/version)能用是因为它们读的是登录时已加载进 JS 的状态,而非实时网络。
**修复**:`dao_eda_cdp_driver.heal_service_workers(ws)` —— 注销 SW + 重载页面,编辑器自身网络与 REST 全部恢复。已接入 `cold_start.py`(登录确认后自动 heal),并提供 CLI:`python dao_eda_cdp_driver.py heal`。

## 三、已测绘并验证可用的 REST 端点(带 cookie)

| 方法 | 端点 | 用途 | 验证 |
|---|---|---|---|
| GET | `/api/user` | 当前用户(uuid/username/telephone…) | ✓ |
| GET | `/api/teams` | 团队列表 | ✓ |
| GET | `/api/projects?page=1&pageSize=4000` | 工程列表(`result.lists[]`) | ✓ 列出 8+ 工程 |
| GET | `/api/folder/getUserFolderAllData` | 个人文件夹树 | ✓ |
| POST | `/api/v4/projects/add` | 新建工程 → `result.uuid` | ✓ 实测创建成功 |
| (其它) | `/api/system/config` `/api/categories` `/api/v2/devices` `/api/v2/eda/product/search` … | 登录后页面自然调用,待按需测绘 | — |

`POST /api/v4/projects/add` 请求体(实测):
```json
{"name":"<名>","public":false,"user_uuid":"<uuid>","cbb_project":false,
 "introduction":"","content":"","default_sheet":"",
 "project_path":"<username>/<slug>","mode":1}
```
**删除端点**:`/api/projects/{uuid}` 存在(DELETE 返回 405,故动词非 DELETE),其余猜测 404;需抓 GUI 真实删除请求确认,暂不实现以免误删。

## 四、extapi(`_EXTAPI_ROOT_`)层现状

- 全量目录:`eda_api_catalog.json`(94 命名空间 / 701 方法,`eda_api_catalog.py` 自省生成)。
- 绑定:`eda_api.py`——属性即命名空间、直调即接口、字符串寻址、`.map()` 多并发、自动重连、对照目录告警。
- **读类 API 实测可用**(身份、版本、语言、工作区、团队、渲染查询等),并发调用通过。
- **编辑器内写类 API**(放件/连线/PCB)需先有工程/文档**打开**才有意义 → 下一步:经 REST 建工程后,用编辑器层打开并在其中操作,跑通「执行→反馈(取画布图)→呈现」闭环。

## 五、下一步(Phase 4.3 / 4.4)

1. 打通"打开指定工程到编辑器"(URL 直达 or extapi `openProject`/`openDocument`),使编辑器层有上下文。
2. 在工程内:新建原理图 → 放置元件(`sch_PrimitiveComponent` / `lib_Device` 搜索)→ `dmt_EditorControl.getCurrentRenderedAreaImage` 取图回传。
3. 据此层层递进到大型 PCB 全流程(布局/布线/DRC/Gerber/BOM),边实践边补齐 REST/extapi 测绘。
