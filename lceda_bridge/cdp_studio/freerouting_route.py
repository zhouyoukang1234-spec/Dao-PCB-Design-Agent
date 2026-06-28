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