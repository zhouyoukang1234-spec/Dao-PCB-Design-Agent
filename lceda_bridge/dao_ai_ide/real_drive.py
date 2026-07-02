#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_drive — 用真实外接 API(DeepSeek/小米MiMo)驱动已安装的 DAO AI IDE 原生面板。

前置: 扩展已经 install_eext.py 装入并随 EDA 加载(顶部有「DAO AI」菜单)。
流程: 顶帧 localStorage 落真实模型配置 → 经原生菜单打开面板 → 找到 blob 同源
iframe → 注入用户消息并点发送 → 轮询直到 AI 最终回复(真实 LLM + 工具调用直驱引擎)。

用法:
  DAO_LLM_BASE=https://api.deepseek.com DAO_LLM_KEY=sk-... DAO_LLM_MODEL=deepseek-chat \
  DAO_MSG='在EDA里弹出一条提示...' python3 real_drive.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cdp_studio"))
import dao_eda_cdp_driver as d

PORT = int(os.environ.get("DAO_CDP_PORT", "29230"))
BASE = os.environ.get("DAO_LLM_BASE", "https://api.deepseek.com")
KEY = os.environ.get("DAO_LLM_KEY", "")
MODEL = os.environ.get("DAO_LLM_MODEL", "deepseek-chat")
NAME = os.environ.get("DAO_LLM_NAME", "DeepSeek")
MSG = os.environ.get("DAO_MSG", "请获取当前EDA上下文,并在界面弹出一条提示说明你已就绪")
TIMEOUT = int(os.environ.get("DAO_TIMEOUT", "180"))


def ev(ws, js, ap=False, t=30):
    out, err = d.evaluate(ws, js, await_promise=ap, timeout=t)
    if err:
        raise RuntimeError(err)
    return out


def main():
    ws = d.connect_editor(PORT)

    models = [
        {"id": "m_deepseek", "name": "DeepSeek", "base": "https://api.deepseek.com",
         "key": os.environ.get("DAO_DEEPSEEK_KEY", KEY), "model": "deepseek-chat", "temp": 0.3},
        {"id": "m_mimo", "name": "小米MiMo", "base": "https://api.xiaomimimo.com/v1",
         "key": os.environ.get("DAO_MIMO_KEY", ""), "model": "mimo-v2.5", "temp": 0.3},
    ]
    active = "m_deepseek" if NAME.lower().startswith("deep") else "m_mimo"
    seed = """(function(){
      localStorage.setItem('dao.ai.ide.models', %s);
      localStorage.setItem('dao.ai.ide.activeModel', %s);
      return 'seeded';
    })()""" % (json.dumps(json.dumps(models)), json.dumps(json.dumps(active)))
    print("seed:", ev(ws, seed))

    # 关掉已开面板(若有),再经原生菜单重开,让面板读到新模型配置
    ev(ws, """(function(){
      var f=Array.from(document.querySelectorAll('iframe')).find(function(x){return (x.src||'').indexOf('blob:')===0;});
      if(f){var dlg=f.closest('[class*=dialog],[class*=Dialog],[class*=window]');
        var btn=dlg&&dlg.querySelector('[class*=close],[title*=关闭]');
        if(btn) btn.click(); else if(dlg) dlg.remove(); else f.remove();}
      return 'closed';
    })()""")
    time.sleep(1)
    print("menu:", ev(ws, """(function(){
      var els=Array.from(document.querySelectorAll('span,div')).filter(function(e){return e.textContent==='DAO AI'&&e.children.length===0;});
      if(!els.length) return 'no menu';
      ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){els[0].dispatchEvent(new MouseEvent(t,{bubbles:true}));});
      return 'menu clicked';
    })()"""))
    time.sleep(1)
    print("item:", ev(ws, """(function(){
      var it=Array.from(document.querySelectorAll('span,div,li')).filter(function(e){return e.textContent==='打开 AI IDE'&&e.children.length===0;});
      if(!it.length) return 'no item';
      ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){it[0].dispatchEvent(new MouseEvent(t,{bubbles:true}));});
      return 'item clicked';
    })()"""))
    time.sleep(3)

    # 面板内: 新建会话→注入消息→发送
    drive = """(function(){
      var f=Array.from(document.querySelectorAll('iframe')).find(function(x){return (x.src||'').indexOf('blob:')===0;});
      if(!f) return 'no panel iframe';
      var doc=f.contentWindow.document;
      var nb=doc.getElementById('newSess'); if(nb) nb.click();
      var input=doc.getElementById('input'), send=doc.getElementById('send');
      if(!input||!send) return 'no input/send';
      input.value=%s;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      send.click();
      return 'sent';
    })()""" % (json.dumps(MSG),)
    print("drive:", ev(ws, drive))

    # 轮询: busy 结束(send 按钮回到「发送」)且最后一条为 assistant 文本
    t0 = time.time()
    final = None
    while time.time() - t0 < TIMEOUT:
        time.sleep(3)
        out = ev(ws, """(function(){
          var f=Array.from(document.querySelectorAll('iframe')).find(function(x){return (x.src||'').indexOf('blob:')===0;});
          if(!f) return JSON.stringify({err:'no iframe'});
          var doc=f.contentWindow.document;
          var send=doc.getElementById('send');
          var msgs=Array.from(doc.querySelectorAll('#msgs .msg'));
          var last=msgs[msgs.length-1];
          var tcs=doc.querySelectorAll('#msgs .toolcall').length;
          var lastTxt=last?(last.querySelector('.content')?last.querySelector('.content').textContent:''):'';
          var lastRole=last?last.className.replace('msg ',''):'';
          return JSON.stringify({busy:send&&send.textContent==='停止',n:msgs.length,toolcalls:tcs,lastRole:lastRole,lastTxt:lastTxt.slice(0,400)});
        })()""")
        st = json.loads(out)
        print("poll:", st)
        if not st.get("busy") and st.get("lastRole") == "assistant":
            final = st
            break
        if not st.get("busy") and time.time() - t0 > 15:
            # 回路已停但末条非 assistant(不应发生,面板已兜底补结语) → 记录并退出
            final = st
            break
    print("FINAL:", json.dumps(final, ensure_ascii=False))
    if not final:
        sys.exit(1)


if __name__ == "__main__":
    main()
