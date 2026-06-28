"""外部布线器(Freerouting)闭环编排:EasyEDA DSN 出 → Freerouting 布线 → SES 回灌 EasyEDA。

道:嘉立创内置自动布线器是"够用",Freerouting 是业界最强开源布线器;把二者接成一条
程序化闭环,等于给本系统接上一个可替换的"外部大脑"。本会话攻克的三段边界(全部已硬验证):

  1. **DSN 出**:`Flow.export_dsn` 从**未布线**板导出标准 Specctra DSN(已布线板导出会层名错配)。
  2. **Freerouting**:`java -jar freerouting.jar -de in.dsn -do out.ses` 跑批布线、自动写 SES。
     v1.9.0 在有显示器时会弹 GUI 确认框("Autorouter is about to start"),用 SendKeys 回车自动确认;
     布完即按 -do 路径落 SES 并退出。
  3. **SES 回**:`Flow.import_ses` 把 SES 字节 in-page 构造成浏览器 File 直传 `importAutoRouteSesFile`。

用法:先用 dao_board 造好**未布线**的板(scaffold/place/wire/sync + auto_board_outline),
再 `python freerouting_route.py`(脚本里改 PCB 句柄或在已打开的板上跑)。
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eda_flow

HOME = os.path.expanduser("~")
JAVA = os.path.join(HOME, "jre_extracted", "jdk-21.0.11+10-jre", "bin", "java.exe")
JAR = os.path.join(HOME, "freerouting.jar")


def _win(p):
    """MSYS/绝对路径 → Freerouting(原生 Windows)能认的反斜杠路径。"""
    return os.path.abspath(p)


def _auto_confirm_dialogs(rounds=6, gap=1.5):
    """Freerouting v1.9.0 弹 GUI 确认框时,用 PowerShell SendKeys 回车逐个确认(无显示器可省)。"""
    titles = ["DSN file reader - Freerouting", "Autorouter confirmation - Freerouting"]
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic,System.Windows.Forms; "
          + "; ".join(
              "try{ [Microsoft.VisualBasic.Interaction]::AppActivate('%s'); "
              "Start-Sleep -Milliseconds 400; "
              "[System.Windows.Forms.SendKeys]::SendWait('{ENTER}') }catch{}" % t
              for t in titles))
    for _ in range(rounds):
        subprocess.run(["powershell", "-Command", ps], capture_output=True)
        time.sleep(gap)


def run_freerouting(dsn_path, ses_path, max_passes=6, wait_s=40):
    """跑 Freerouting:启动 jar(后台)→ 自动确认 GUI 框 → 轮询 SES 落地。返回 SES 路径或 None。"""
    if os.path.exists(ses_path):
        os.remove(ses_path)
    proc = subprocess.Popen(
        [JAVA, "-jar", _win(JAR), "-de", _win(dsn_path), "-do", _win(ses_path),
         "-mp", str(max_passes)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        _auto_confirm_dialogs(rounds=1, gap=1.0)
        if os.path.exists(ses_path) and os.path.getsize(ses_path) > 200:
            time.sleep(1)
            break
        time.sleep(2)
    try:
        proc.terminate()
    except Exception:
        pass
    return ses_path if os.path.exists(ses_path) else None


def _bump_clearance(dsn_path, clear_mil):
    """把 DSN 的 (rule(clear 6.03...)) 间距统一抬到 clear_mil。

    本会话攻克的**规则对齐**边界:嘉立创导出的 DSN 默认 clearance=6.03mil,Freerouting 会贴着
    6mil 布,落回 EasyEDA 后 JLCPCB DRC(6mil 下限)边界处零容差 → 几处违规。把 DSN 间距**预抬**到
    8.5mil 让 Freerouting 留余量,布完落回即 **DRC 全过**(NE555 实测 6.03→DRC False,8.5→DRC True)。
    """
    import re
    txt = open(dsn_path, "r", encoding="utf-8", errors="ignore").read()
    txt = re.sub(r"\(clear\s+[\d.]+", "(clear %s" % clear_mil, txt)
    open(dsn_path, "w", encoding="utf-8").write(txt)


def route_with_freerouting(base="DAO_FR", clear_mil=8.5):
    """在**当前已打开的未布线 PCB**上跑完整闭环。返回 {dsn, ses, tracks, drc}。

    clear_mil:预抬 DSN 间距给 Freerouting 留余量,确保落回 EasyEDA 后过 JLCPCB DRC(见 _bump_clearance)。
    """
    f = eda_flow.Flow()
    dsn = os.path.join(HOME, base + ".dsn")
    ses = os.path.join(HOME, base + ".ses")
    f.export_dsn(dsn, name=base)
    if clear_mil:
        _bump_clearance(dsn, clear_mil)
    out = run_freerouting(dsn, ses)
    if not out:
        return {"dsn": dsn, "ses": None, "tracks": 0, "drc": False, "err": "freerouting no SES"}
    tracks = f.import_ses(ses)
    f.eda.call("pcb_Document.save", timeout=20)
    time.sleep(1)
    try:
        drc = f.drc_check(timeout=90)
    except Exception as ex:
        drc = "ERR:" + str(ex)[:50]
    return {"dsn": dsn, "ses": ses, "tracks": tracks, "drc": drc}


if __name__ == "__main__":
    import json
    print(json.dumps(route_with_freerouting(), ensure_ascii=False))
