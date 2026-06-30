#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_extapi_dts — 全量逆流嘉立创EDA Pro EXTAPI 声明面（一次性·一劳永逸）。

解析桌面/Web 客户端自带的 TypeScript 声明 `api-types.d.ts`，提取**每个**命名空间、
**每个**方法的「完整带类型签名 + 文档描述」，并与运行期 `_EXTAPI_ROOT_` introspection
（`_extapi_full_map.json`：实际可达方法名）交叉核对，标注每个方法是否 live 可达。

产物（机器可读唯一事实源 + 人/Agent 可读总览）：
  extapi_full_catalog.json   完整结构化目录（namespace×method×签名×文档×live）
  EXTAPI_REFERENCE.md        按模块分组的可读参考

命名空间映射经 `EDA` 根类源码核实：root 暴露的属性名 == 类名首段小写
（PCB_Drc→pcb_Drc, LIB_Device→lib_Device, …），非臆测。

用法:
  python extract_extapi_dts.py [path/to/api-types.d.ts]
默认在客户端安装目录下自动定位最新 pro-api 版本的 api-types.d.ts。
"""
import re, json, os, sys, glob, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_MAP = os.path.join(HERE, "_extapi_full_map.json")
OUT_JSON = os.path.join(HERE, "extapi_full_catalog.json")
OUT_MD = os.path.join(HERE, "EXTAPI_REFERENCE.md")

# 模块前缀 → 中文分组名
MODULE = {
    "dmt": "DMT · 工程/编辑器/团队/工作区",
    "lib": "LIB · 元件库（器件/封装/符号/3D/立创商城）",
    "pcb": "PCB · 印制板（图元/层/网络/DRC/制造/3D）",
    "sch": "SCH · 原理图（图元/网络/网表/DRC/仿真/制造）",
    "pnl": "PNL · 拼板",
    "sys": "SYS · 系统（文件/对话框/存储/环境/消息/窗口/单位…）",
    "eDA": "EDA · 根对象",
}


def find_dts():
    pats = [
        "/home/ubuntu/lceda/client/lceda-pro/resources/app/assets/pro-api/*/api-types.d.ts",
        os.path.expanduser("~/lceda/client/**/api-types.d.ts"),
        "/opt/**/api-types.d.ts",
    ]
    for p in pats:
        hits = sorted(glob.glob(p, recursive=True))
        if hits:
            return hits[-1]
    return None


def rpc_ns(cls):
    if "_" in cls:
        head, rest = cls.split("_", 1)
        return head.lower() + "_" + rest
    return cls[0].lower() + cls[1:]


def parse(src_path):
    lines = open(src_path, encoding="utf-8").read().split("\n")
    n = len(lines)
    class_re = re.compile(r"^declare class (\w+)(?:\s+(?:extends|implements)\s+([\w, ]+))?\s*\{")
    classes = []
    i = 0
    while i < n:
        m = class_re.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        inherit = (m.group(2) or "").strip()
        depth = lines[i].count("{") - lines[i].count("}")
        j = i + 1
        while j < n and depth > 0:
            depth += lines[j].count("{") - lines[j].count("}")
            j += 1
        classes.append({"name": name, "inherit": inherit, "body": lines[i + 1:j - 1]})
        i = j
    return classes


def parse_methods(body):
    methods, k, m = [], 0, len(body)
    last_doc = None
    while k < m:
        s = body[k].strip()
        if s.startswith("/**"):
            doc_lines = []
            while k < m and "*/" not in body[k]:
                doc_lines.append(body[k]); k += 1
            if k < m:
                doc_lines.append(body[k]); k += 1
            desc = ""
            for dl in doc_lines:
                t = dl.strip().lstrip("/*").strip()
                if t and not t.startswith("@") and t != "*":
                    t = t.lstrip("*").strip()
                    if t:
                        desc = t; break
            last_doc = desc
            continue
        mm = re.match(r"(?:public\s+|static\s+|readonly\s+|abstract\s+|get\s+|set\s+)*(\w+)\s*[(<]", s)
        is_priv = bool(re.match(r"(private|protected)\b", s))
        if mm and not is_priv and not s.startswith("//") and not s.startswith("*"):
            # .d.ts 声明无方法体；按括号深度累计多行签名（含 Promise<{...}> 内联对象类型），
            # 直到深度归零且以分号结束。
            sig, depth = "", 0
            while k < m:
                ln = body[k]
                sig += ((" " if sig else "") + ln.strip())
                depth += (ln.count("(") + ln.count("[") + ln.count("{")
                          - ln.count(")") - ln.count("]") - ln.count("}"))
                if depth <= 0 and sig.rstrip().endswith(";"):
                    break
                k += 1
            sig = re.sub(r"\s+", " ", sig).strip().rstrip(";").strip()
            mname = mm.group(1)
            if mname != "constructor" and "(" in sig:
                methods.append({"name": mname, "signature": sig, "doc": last_doc or ""})
            last_doc = None
        k += 1
    return methods


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else find_dts()
    if not src or not os.path.exists(src):
        print("api-types.d.ts not found; pass path as arg"); sys.exit(1)
    api_ver = os.path.basename(os.path.dirname(src))
    runtime = {}
    if os.path.exists(RUNTIME_MAP):
        try:
            runtime = json.load(open(RUNTIME_MAP, encoding="utf-8"))
        except Exception:
            runtime = {}

    classes = parse(src)
    namespaces, data_types = {}, {}
    for c in classes:
        meths = parse_methods(c["body"])
        if c["name"].startswith("I"):           # I* 为返回/数据类型
            data_types[c["name"]] = {"inherit": c["inherit"], "methods": meths}
            continue
        ns = rpc_ns(c["name"])
        live_names = set(runtime.get(ns) or [])
        for mth in meths:
            mth["live"] = (mth["name"] in live_names) if live_names else None
        namespaces[ns] = {
            "class": c["name"], "inherit": c["inherit"],
            "module": ns.split("_", 1)[0] if "_" in ns else ns,
            "runtime_known": ns in runtime,
            "methods": meths,
        }

    nm = sum(len(v["methods"]) for v in namespaces.values())
    dm = sum(len(v["methods"]) for v in data_types.values())
    catalog = {
        "source": "JLCEDA Pro EXTAPI TypeScript declaration (api-types.d.ts)",
        "api_version": api_ver,
        "generated": datetime.date.today().isoformat(),
        "namespace_count": len(namespaces),
        "namespace_method_count": nm,
        "data_type_count": len(data_types),
        "data_type_method_count": dm,
        "root_mapping": "EDA root class exposes each namespace as lowercase-first-segment of class name (verified vs source)",
        "namespaces": namespaces,
        "data_types": data_types,
    }
    json.dump(catalog, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- 生成可读 markdown 参考 ----
    md = []
    md.append("# 嘉立创EDA Pro EXTAPI 完整能力参考")
    md.append("")
    md.append("> 一次性全量逆流·一劳永逸。自 `api-types.d.ts`（TypeScript 声明，权威）解析，"
              "与运行期 `_EXTAPI_ROOT_` introspection 交叉核对 live 可达性。")
    md.append(">")
    md.append(f"> - API 版本：`{api_ver}`　生成：`{catalog['generated']}`")
    md.append(f"> - 命名空间 **{len(namespaces)}** 个，可直接 RPC 调用方法 **{nm}** 个；"
              f"返回/数据类型 **{len(data_types)}** 个（链式方法 {dm} 个）。")
    md.append(f"> - 根映射：`EDA` 根类把每个命名空间以「类名首段小写」暴露"
              "（`PCB_Drc`→`pcb_Drc`），经源码核实。")
    md.append(f"> - 调用：`driver._call('<namespace>.<method>', *args)`（见 `dao_rpc_driver.py`）。")
    md.append("")
    md.append("## 模块索引")
    md.append("")
    by_mod = {}
    for ns, v in namespaces.items():
        by_mod.setdefault(v["module"], []).append(ns)
    for mod in ["dmt", "lib", "pcb", "sch", "pnl", "sys", "eDA"]:
        if mod in by_mod:
            cnt = sum(len(namespaces[x]["methods"]) for x in by_mod[mod])
            md.append(f"- **{MODULE.get(mod, mod)}** — {len(by_mod[mod])} 命名空间 / {cnt} 方法")
    md.append("")

    for mod in ["dmt", "lib", "pcb", "sch", "pnl", "sys", "eDA"]:
        if mod not in by_mod:
            continue
        md.append(f"## {MODULE.get(mod, mod)}")
        md.append("")
        for ns in sorted(by_mod[mod]):
            v = namespaces[ns]
            live = sum(1 for x in v["methods"] if x.get("live"))
            tag = f"（live 可达 {live}/{len(v['methods'])}）" if v["runtime_known"] else "（运行期未抽样）"
            md.append(f"### `{ns}` · {v['class']} {tag}")
            md.append("")
            if not v["methods"]:
                md.append("_（无公开方法）_"); md.append(""); continue
            md.append("| 方法 | 签名 | 说明 | live |")
            md.append("|---|---|---|:--:|")
            for mth in v["methods"]:
                lv = "✓" if mth.get("live") else ("·" if mth.get("live") is False else "?")
                sig = mth["signature"].replace("|", "\\|")
                doc = (mth["doc"] or "").replace("|", "\\|")
                md.append(f"| `{mth['name']}` | `{sig}` | {doc} | {lv} |")
            md.append("")

    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")

    print("api_version:", api_ver)
    print("namespaces:", len(namespaces), "methods:", nm)
    print("data_types:", len(data_types), "methods:", dm)
    live_total = sum(1 for v in namespaces.values() for x in v["methods"] if x.get("live"))
    known_ns = sum(1 for v in namespaces.values() if v["runtime_known"])
    print("runtime-known namespaces:", known_ns, "| live-confirmed methods:", live_total)
    print("wrote:", OUT_JSON)
    print("wrote:", OUT_MD)


if __name__ == "__main__":
    main()
