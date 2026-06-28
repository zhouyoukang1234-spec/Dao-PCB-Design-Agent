    def route_export(self, out_base=None, margin=60):
        f = eda_flow.Flow()
        f.open_project(self.state["project"])
        f.open_document(self.state["pcb"])
        time.sleep(2)
        if not f.has_board_outline():
            bo = f.auto_board_outline(margin=margin)
            f.eda.call("pcb_Document.save", timeout=20)
            time.sleep(1)
        else:
            bo = {"existing": True}
        f.reload_and_reopen(self.state["project"], self.state["pcb"])
        f.prepare_pcb_nets()
        time.sleep(2)
        dps = getattr(self, "_diff_pairs", []) or []
        diff = None
        if dps:
            diff = {}
            for nm, pos, neg in dps:
                diff[nm] = f.create_diff_pair(nm, pos, neg)
            f.eda.call("pcb_Document.save", timeout=20)
            time.sleep(1)
        route = f.autoroute_gui(wait=18)
        # 线宽:先默认布通,再**布线后**逐条加粗目标网铜线(规则法会让布线器罢工,见 widen_net_tracks)
        widths = getattr(self, "_net_widths", {}) or {}
        widened = None
        if widths:
            widened = {}
            for w_mil, grp in _group_by_width(widths):
                widened[str(w_mil)] = f.widen_net_tracks(w_mil, grp)
            f.eda.call("pcb_Document.save", timeout=20)
            time.sleep(1)
        pour = None
        if getattr(self, "_ground_pour", False):
            try:
                pour = f.auto_ground_pour(net="GND", layers=(1, 2))
                f.eda.call("pcb_Document.save", timeout=20)
            except Exception as e:
                pour = "ERR:" + str(e)[:60]
        try:
            drc = f.drc_check(timeout=120)
        except Exception as e:
            drc = "ERR:" + str(e)[:50]
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               (out_base or self.state.get("name", "Dao")) + "_fab")
        exp = f.export_all(out_dir, base=out_base or self.state.get("name", "Dao"))
        return {"outline": bo, "diff": diff, "widened": widened, "route": route, "pour": pour, "drc": drc, "export_dir": out_dir,
                "export": {k: (v.get("size") if isinstance(v, dict) else v) for k, v in exp.items()}}

    # ---- 一键全流程 ----
    def build(self, spec, margin=60):
        report = {"spec": spec.name}
        report["scaffold"] = {k: self.scaffold(spec)[k] for k in ("project", "pcb", "sch_page")}
        report["place"] = self.place(spec)
        report["wire"] = self.wire(spec)
        report["sync"] = self.sync(spec)
        self._ground_pour = getattr(spec, "ground_pour", False)
        self._net_widths = getattr(spec, "net_widths", {})
        self._diff_pairs = getattr(spec, "diff_pairs", [])
        report["route_export"] = self.route_export(out_base=spec.name, margin=margin)