# cdp_studio — 嘉立创EDA Pro Web 冷启动 + CDP 直驱底座

> 道法自然 · 无为而无不为 —— 全新 VM 跑一条命令，即落到"已登录、`_EXTAPI_ROOT_`
> 可直驱"的编辑器状态，后续 Agent 像 Cursor 写代码一样直接操作 EDA 全模块。

## 这是什么

嘉立创EDA专业版 **Web 编辑器**(`https://pro.lceda.cn/editor`，V3)把整套**官方扩展 API**
挂在主页面全局 `window._EXTAPI_ROOT_` 上。于是无需安装/激活扩展、无需扩展沙箱自建
WebSocket，只要经 Chrome 远程调试(CDP)在**主页面上下文** `Runtime.evaluate` 调用
`_EXTAPI_ROOT_.<命名空间>.<方法>(...)`，即可用 EDA 自己的机制完成新建工程/原理图、放件、
移动、并用 `dmt_EditorControl.getCurrentRenderedAreaImage()` 取画布实时图回传。

执行面(Agent 下指令) → EDA 真实变化 → 反馈/呈现面(截图/状态回传)，三面归一。

## 文件

| 文件 | 作用 |
|---|---|
| `dao_eda_cdp_driver.py` | 极简 CDP 客户端(无第三方依赖) + `_EXTAPI_ROOT_` 调用封装(`call_eda`/`probe`/`capture_canvas`) |
| `cdp_nav.py` | 导航/截图/查 target 的小工具 |
| `jlc_login.py` | 经 CDP 驱动 `passport.jlc.com` 登录(手机号短信 / 账号密码) |
| `jlc_session.py` | 登录态(cookies + 鉴权 localStorage)的**快照/恢复**——冷启动免登录核心 |
| `cold_start.py` | **一键冷启动编排**:开编辑器→已登录?→注入登录态→账号密码登录→校验 |

## 冷启动:全新 VM 一条命令

```bash
python lceda_bridge/cdp_studio/cold_start.py
```

逐级回退,直到"已登录"为止:

1. 复用 **Devin 托管的 Chrome CDP**(默认 `:29229`,随会话常驻,无需自起)。
2. 打开/切到 `pro.lceda.cn/editor`;已登录则直接完成。
3. 用 `JLC_SESSION_B64`(或本地 `~/.dao/jlc_session.json`)**注入登录态** → 多数情况下零登录直接进。
4. 仍未登录且有 `JLC_PHONE` + `JLC_PASSWORD` → **账号密码自动登录**。
5. 登录成功后自动刷新本地会话快照,便于下次零登录。

> 若嘉立创对新设备触发**滑块/短信风控**,第 4 步会返回 `NEED_SMS` 提示,此时需**一次**
> 人工短信验证(见下"手工登录")。验证后 `jlc_session.py save` 固化,后续又回到零登录。

### 所需 secret(用户级,已随会话注入为环境变量)

| 环境变量 | 含义 |
|---|---|
| `JLC_PHONE` | 登录手机号 |
| `JLC_PASSWORD` | 登录密码(满足嘉立创策略:6-12 位含数字+大小写字母) |
| `JLC_SESSION_B64` | 已登录态快照(base64),注入即免登录 |

> 仓库内**不存任何明文凭据/cookie**;一切走加密 secret 注入。本地快照落在
> `~/.dao/jlc_session.json`(在仓库之外,不入库)。

## 手工登录(仅当风控需要一次人工时)

```bash
python jlc_login.py open                 # 在编辑器点 Login 打开登录页
python jlc_login.py tab 手机号            # 切到手机号登录
python jlc_login.py phone <手机号>        # 填手机号
python jlc_login.py sendcode             # 获取验证码(用户收短信)
python jlc_login.py code <6位验证码>      # 填验证码并提交
python jlc_session.py save               # 固化登录态(下次零登录)
```

## 直驱 EDA(登录后)

```bash
python dao_eda_cdp_driver.py probe                               # 探测 _EXTAPI_ROOT_ 与命名空间
python dao_eda_cdp_driver.py call "dmt_Project.getAllProjectsUuid" '[]'
python dao_eda_cdp_driver.py call "dmt_Project.getCurrentProjectInfo" '[]'
python dao_eda_cdp_driver.py shot canvas.png                     # 取当前画布渲染图
```

## 环境变量

- `DAO_CDP_PORT` Chrome 远程调试端口(默认 `29229`)
- `JLC_SESSION_FILE` 本地会话快照路径(默认 `~/.dao/jlc_session.json`)
- `JLC_LS_CAP` 快照里单个 localStorage 值的最大字节(默认 20000,丢弃 UI 大缓存)
