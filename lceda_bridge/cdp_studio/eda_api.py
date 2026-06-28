#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eda_api — 嘉立创EDA Pro Web **编辑器层**高层绑定(经 CDP 调 `_EXTAPI_ROOT_`)。

  eda = EDA()
  eda.call("dmt_Project.getCurrentProjectInfo")          # 字符串寻址
  eda.dmt_Project.getCurrentProjectInfo()                # 属性寻址(等价)
  eda.map(["sys_Environment.getEditorCurrentVersion",    # 多调用(顺序)
           "dmt_Project.getAllProjectsUuid"])
  eda.reconnect()                                        # reload 后重连执行上下文

注:`_EXTAPI_ROOT_.dmt_Project.createProject` 在编辑器页是空操作;账号级工程 CRUD
走 `eda_rest.py`。编辑器层只管**已打开**工程内的图元/渲染。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dao_eda_cdp_driver as d


class EDA:
    def __init__(self, session=None, url_hint=d.EDITOR_HINT):
        self.url_hint = url_hint
        self.session = session or d._editor_session(url_hint=url_hint)

    # ---- 连接管理 ---------------------------------------------------------- #
    def reconnect(self):
        """整页 reload 后旧执行上下文失效 → 重新连到 editor page。"""
        try:
            self.session.close()
        except Exception:
            pass
        self.session = d._editor_session(url_hint=self.url_hint)
        return self

    @property
    def ws(self):
        return self.session

    # ---- 调用 -------------------------------------------------------------- #
    def call(self, dotted, *args, timeout=30, await_promise=True, retries=2):
        last = None
        for i in range(retries + 1):
            try:
                return d.call_eda(self.session, dotted, *args, await_promise=await_promise, timeout=timeout)
            except Exception as e:
                last = e
                msg = str(e)
                # 仅对传输层超时/连接问题重连重试;业务错误直接抛
                if "EVAL_TRANSPORT" in msg or "CDP timeout" in msg or "WS" in msg or "closed" in msg:
                    try:
                        self.reconnect()
                    except Exception:
                        pass
                    continue
                raise
        raise last

    def map(self, dotted_list, timeout=30):
        """顺序执行多个调用(各自字符串或 [dotted, *args])。返回 list。"""
        out = []
        for item in dotted_list:
            if isinstance(item, (list, tuple)):
                out.append(self._safe(item[0], *item[1:], timeout=timeout))
            else:
                out.append(self._safe(item, timeout=timeout))
        return out

    def _safe(self, dotted, *args, timeout=30):
        try:
            return {"m": dotted, "v": self.call(dotted, *args, timeout=timeout)}
        except Exception as e:
            return {"m": dotted, "err": str(e)[:160]}

    # ---- 属性寻址 ---------------------------------------------------------- #
    def __getattr__(self, ns):
        if ns.startswith("_") or ns in ("session", "url_hint"):
            raise AttributeError(ns)
        return _Namespace(self, ns)

    # ---- 测绘 -------------------------------------------------------------- #
    def catalog(self):
        """全量测绘 _EXTAPI_ROOT_:命名空间→方法名+arity。返回 dict。"""
        js = r"""JSON.stringify((function(){
          var R=window._EXTAPI_ROOT_; if(!R) return {};
          var out={};
          Object.keys(R).forEach(function(ns){
            try{
              var o=R[ns]; if(!o) return;
              var names={};
              var proto=Object.getPrototypeOf(o)||{};
              Object.getOwnPropertyNames(proto).concat(Object.keys(o)).forEach(function(k){
                if(k==='constructor') return;
                try{ var v=o[k]; if(typeof v==='function'){ names[k]=v.length; } }catch(e){}
              });
              out[ns]={type:typeof o, methods:names};
            }catch(e){ out[ns]={err:String(e)}; }
          });
          return out;
        })())"""
        v, e = d.evaluate(self.session, js, timeout=30)
        if e:
            raise RuntimeError("catalog: %s" % e)
        return json.loads(v)


class _Namespace:
    def __init__(self, eda, ns):
        self._eda = eda
        self._ns = ns

    def __getattr__(self, method):
        ns, m = self._ns, method

        def _call(*args, timeout=30):
            return self._eda.call("%s.%s" % (ns, m), *args, timeout=timeout)
        return _call


if __name__ == "__main__":
    eda = EDA()
    if len(sys.argv) > 1 and sys.argv[1] == "catalog":
        cat = eda.catalog()
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eda_api_catalog.full.json")
        json.dump(cat, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
        nmeth = sum(len(v.get("methods", {})) for v in cat.values() if isinstance(v, dict))
        print(json.dumps({"namespaces": len(cat), "methods": nmeth, "out": out}, ensure_ascii=False))
    else:
        print(json.dumps(eda.map([
            "sys_Environment.getEditorCurrentVersion",
            "dmt_Project.getCurrentProjectInfo",
        ]), ensure_ascii=False))
