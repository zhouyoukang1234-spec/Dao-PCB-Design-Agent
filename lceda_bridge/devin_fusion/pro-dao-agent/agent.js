/*
 * pro-dao-agent · 嘉立创 EDA 原生 Devin Agent 侧栏（半原生 Devin Desktop）
 *
 * 本文件同时服务两条落地路径（道·甲乙同构）：
 *   甲·非破坏：由 dao_devin_inject.py 经 CDP Runtime.evaluate 注入到 EDA 活体窗口。
 *   乙·原生扩展：作为 assets/pro-dao-agent/<ver>/agent.js 由嘉立创扩展系统加载。
 *
 * 它把「Devin Cloud 归一网页 /shell」(browser-in-browser：对话/账号/切号/反向注入/MCP/Proxy Pro)
 * 挂成嘉立创软件内的一张悬浮/停靠面板 → 软件内无感调用 Devin Cloud。
 *
 * ★关键机制（活体坐实）：嘉立创是 Electron，渲染进程**禁止子 iframe 导航到外部源**
 *   （webview 不支持、`iframe.src=外链` 永远停在 about:blank，且会把该 frame 变成跨源死帧）。
 *   故不走 iframe.src，而是：
 *     1) 由宿主页(https://client)用 fetch(BASE+'/shell') 取归一网页 HTML（服务端 CORS:* 放行）；
 *     2) 把其中相对的 /api/shell/* 改写为绝对 BASE/api/shell/*（跨源轮询/SSE 靠 CORS:* 通）；
 *     3) 写进一个**从未设过外链 src 的同源 iframe**（document.write）→ 归一网页在 EDA 进程内原样运行。
 *
 * 宿主 URL 来源（可达性回退）：window.__DAO_DEVIN_URL__ → localStorage['dao.devin.url'] → 默认 127.0.0.1:9920。
 */
(function () {
  "use strict";
  var PANEL_ID = "dao-devin-panel";
  var DEFAULT_HOST = "http://127.0.0.1:9920";
  var SHELL_PATH = "/shell";

  // 归一网页里出现的、需要改写成绝对地址的相对接口前缀
  var API_REWRITE = [/(['"])\/api\/shell\//g, /(['"])\/api\//g];

  function splitBase(url) {
    // 传入可为 http://host:port 或 http://host:port/shell；返回 {base, shell}
    url = String(url || "");
    var m = url.replace(/\/+$/, "");
    if (/\/shell$/.test(m)) return { base: m.slice(0, -("/shell".length)), shell: m };
    return { base: m, shell: m + SHELL_PATH };
  }

  function resolveUrl() {
    try {
      if (window.__DAO_DEVIN_URL__) return String(window.__DAO_DEVIN_URL__);
      var ls = window.localStorage && window.localStorage.getItem("dao.devin.url");
      if (ls) return ls;
    } catch (e) {}
    return DEFAULT_HOST + SHELL_PATH;
  }

  function eject() {
    var old = document.getElementById(PANEL_ID);
    if (old && old.parentNode) old.parentNode.removeChild(old);
    return !!old;
  }

  function mkBtn(txt, title) {
    var b = document.createElement("div");
    b.textContent = txt; b.title = title || "";
    b.style.cssText = "width:22px;height:22px;display:flex;align-items:center;justify-content:center;border-radius:5px;cursor:pointer;color:#c8c8c8";
    b.onmouseenter = function () { b.style.background = "#3a3d42"; };
    b.onmouseleave = function () { b.style.background = "transparent"; };
    return b;
  }

  // 把归一网页 HTML 里的相对接口改写为绝对（跨源靠服务端 CORS:*）
  function rewrite(html, base) {
    var out = html;
    out = out.replace(/(['"])\/api\/shell\//g, "$1" + base + "/api/shell/");
    // EventSource / fetch 里其余 /api/ 也一并绝对化（避免命中宿主 https://client）
    out = out.replace(/(['"])\/api\//g, "$1" + base + "/api/");
    return out;
  }

  // 把归一网页写进同源 iframe（核心：从不给该 iframe 设外链 src）
  function paint(iframe, base, shell) {
    return fetch(shell, { mode: "cors", credentials: "omit" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var d = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
        if (!d) throw new Error("no same-origin iframe document");
        d.open(); d.write(rewrite(html, base)); d.close();
        return true;
      });
  }

  function mount(url) {
    url = url || resolveUrl();
    var sb = splitBase(url);
    eject();

    var wrap = document.createElement("div");
    wrap.id = PANEL_ID;
    wrap.style.cssText = [
      "position:fixed", "top:64px", "right:16px", "width:460px", "height:82vh",
      "z-index:2147483000", "background:#0d1117", "border:1px solid #30363d",
      "border-radius:10px", "box-shadow:0 10px 40px rgba(0,0,0,.55)",
      "display:flex", "flex-direction:column", "overflow:hidden",
      "font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif"
    ].join(";");

    var bar = document.createElement("div");
    bar.style.cssText = "flex:0 0 34px;display:flex;align-items:center;gap:8px;padding:0 10px;background:#161b22;color:#e6edf3;cursor:move;user-select:none;font-size:13px";
    bar.innerHTML = '<span style="font-weight:600">\u261f Devin</span><span style="opacity:.6;font-size:11px">Cloud \u00b7 \u5d4c\u5165\u5f52\u4e00\u7f51\u9875</span>';
    var spacer = document.createElement("div"); spacer.style.flex = "1"; bar.appendChild(spacer);

    var iframe = document.createElement("iframe");
    iframe.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
    iframe.style.cssText = "flex:1;width:100%;border:0;background:#0d1117";
    // 注意：绝不设置 iframe.src=外链（Electron 会拦截并使其变跨源死帧）

    var btnReload = mkBtn("\u27f3", "\u91cd\u8f7d"); btnReload.onclick = function () { paint(iframe, sb.base, sb.shell); };
    var minned = false;
    var btnMin = mkBtn("\u2014", "\u6700\u5c0f\u5316");
    btnMin.onclick = function () { minned = !minned; iframe.style.display = minned ? "none" : "block"; wrap.style.height = minned ? "34px" : "82vh"; };
    var btnClose = mkBtn("\u2715", "\u5173\u95ed"); btnClose.onclick = eject;
    bar.appendChild(btnReload); bar.appendChild(btnMin); bar.appendChild(btnClose);

    wrap.appendChild(bar); wrap.appendChild(iframe);
    (document.body || document.documentElement).appendChild(wrap);

    // 拖拽
    (function drag(handle, box) {
      var sx, sy, ox, oy, on = false;
      handle.addEventListener("mousedown", function (e) {
        on = true; sx = e.clientX; sy = e.clientY;
        var r = box.getBoundingClientRect(); ox = r.left; oy = r.top;
        box.style.right = "auto"; box.style.left = ox + "px"; box.style.top = oy + "px";
        e.preventDefault();
      });
      window.addEventListener("mousemove", function (e) {
        if (!on) return;
        box.style.left = (ox + e.clientX - sx) + "px"; box.style.top = (oy + e.clientY - sy) + "px";
      });
      window.addEventListener("mouseup", function () { on = false; });
    })(bar, wrap);

    // 首绘 + 失败兜底提示
    var p = paint(iframe, sb.base, sb.shell).catch(function (err) {
      try {
        var d = iframe.contentDocument; d.open();
        d.write('<div style="color:#8b949e;font:13px/1.6 sans-serif;padding:24px">Devin \u5f52\u4e00\u7f51\u9875\u52a0\u8f7d\u5931\u8d25\uff1a' + String(err) +
                '<br>\u5bbf\u4e3b\uff1a' + sb.base + '<br>\u8bf7\u786e\u8ba4 DAO Bridge \u53ef\u8fbe\u540e\u70b9 \u27f3 \u91cd\u8f7d\u3002</div>');
        d.close();
      } catch (e) {}
    });

    return { id: PANEL_ID, url: sb.shell, base: sb.base, ready: p };
  }

  var api = {
    mount: mount, eject: eject, resolveUrl: resolveUrl,
    setUrl: function (u) {
      try { window.localStorage.setItem("dao.devin.url", u); } catch (e) {}
      window.__DAO_DEVIN_URL__ = u; return u;
    }
  };
  window.__DAO_DEVIN_PANEL__ = api;

  // 乙·原生扩展入口：若嘉立创扩展系统以 service 方式加载本文件，导出 activate。
  try {
    if (typeof module !== "undefined" && module.exports) {
      module.exports = { activate: function () { return api; }, mount: mount, eject: eject };
    }
  } catch (e) {}

  return api;
})();
