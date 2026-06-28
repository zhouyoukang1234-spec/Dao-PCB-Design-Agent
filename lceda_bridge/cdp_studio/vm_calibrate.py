#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性放件:实输入自标定(会话 2d 实证·突破"合成鼠标非确定"瓶颈)。

★ 核心发现(本会话实证):
  - 编辑器状态栏实时显示光标处的**数据坐标**(X:/Y:),且**真实 OS 输入(computer 工具)**
    移动鼠标会更新它,而 **CDP 合成鼠标事件(Input.dispatchMouseEvent)不更新**(画布只认真输入)。
  - 状态栏既渲染在屏幕、也写进 DOM → 可用 evaluate 直接读,无需截图。
  - 因此:真实鼠标移到若干已知像素 → 读数据坐标 → 最小二乘解出 **像素↔数据 仿射变换**
    → 对任意目标数据坐标算出像素,computer 工具移/点 → **确定性放件**。

★ 实证标定(243% 缩放,computer 工具 1024x768 坐标空间):
    data_x = 5.15 * px_x - 2000 ;  data_y = -3.833 * px_y + 1020
  验证:目标 data(0,0) → 预测像素(388,266) → 实读 X:0 Y:5(误差几 data 单位,可加点细化)。
  注:x/y 比例不同,因 1024x768 computer 空间到真实显示分辨率(~16:9)非等比映射 —— 仿射仍成立。

★ 使用流程(agent 侧):
  1) 视口固定后,用 computer 工具把鼠标移到 ≥3 个像素点(不共线),每次 read_status_xy(ws) 读数据坐标;
  2) coeffs = solve_affine(samples);
  3) 对每个目标器件数据坐标 (Dx,Dy):px = data_to_px(coeffs, Dx, Dy);computer 工具 move/click px 放件;
  4) 任何 pan/zoom 后必须重标定(变换随视口变)。
"""
import sys, re
sys.path.insert(0, ".")
import dao_eda_cdp_driver as d

_STATUS_JS = (
    "(()=>{var els=[...document.querySelectorAll('*')].filter(e=>e.childElementCount===0"
    "&&/^[XY]\\s*[:：]/.test((e.textContent||'').trim()));"
    "var par=els.length?els[0].parentElement:null;"
    "return par?par.innerText.replace(/\\s+/g,' '):'';})()"
)


def read_status_xy(ws):
    """读状态栏数据坐标 -> (x, y) 浮点,读不到返回 None。需鼠标先经真实输入移动过。"""
    v, _e = d.evaluate(ws, _STATUS_JS, await_promise=False, timeout=10)
    if not v:
        return None
    mx = re.search(r"X\s*[:：]\s*(-?\d+(?:\.\d+)?)", v)
    my = re.search(r"Y\s*[:：]\s*(-?\d+(?:\.\d+)?)", v)
    if mx and my:
        return (float(mx.group(1)), float(my.group(1)))
    return None


def _lstsq_1d(px, data):
    """解 data = a*px + b 的最小二乘 (a,b)。px/data 为等长序列。"""
    n = len(px)
    sx = sum(px); sy = sum(data)
    sxx = sum(p * p for p in px); sxy = sum(p * q for p, q in zip(px, data))
    denom = (n * sxx - sx * sx)
    if abs(denom) < 1e-9:
        raise ValueError("退化:像素点共线/重复,无法解此轴")
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


def solve_affine(samples):
    """samples: [(px_x, px_y, data_x, data_y), ...] (≥2,建议 ≥3 不共线)。
    返回 {ax,bx,ay,by}:data_x=ax*px_x+bx ; data_y=ay*px_y+by。"""
    if len(samples) < 2:
        raise ValueError("至少 2 个标定点")
    pxx = [s[0] for s in samples]; pxy = [s[1] for s in samples]
    dx = [s[2] for s in samples]; dy = [s[3] for s in samples]
    ax, bx = _lstsq_1d(pxx, dx)
    ay, by = _lstsq_1d(pxy, dy)
    return {"ax": ax, "bx": bx, "ay": ay, "by": by}


def data_to_px(coeffs, data_x, data_y):
    """目标数据坐标 -> computer 工具像素 (round int)。"""
    px_x = (data_x - coeffs["bx"]) / coeffs["ax"]
    px_y = (data_y - coeffs["by"]) / coeffs["ay"]
    return (int(round(px_x)), int(round(px_y)))


def px_to_data(coeffs, px_x, px_y):
    return (coeffs["ax"] * px_x + coeffs["bx"], coeffs["ay"] * px_y + coeffs["by"])


if __name__ == "__main__":
    # 自检:用本会话实证的 3 点解仿射并验证 data(0,0)->像素
    samples = [(300, 330, -455, -245), (500, 330, 575, -245), (500, 450, 575, -705)]
    c = solve_affine(samples)
    print("coeffs:", c)
    print("data(0,0) -> px:", data_to_px(c, 0, 0), "(实证 ~388,266)")
    print("px(388,266) -> data:", px_to_data(c, 388, 266))
