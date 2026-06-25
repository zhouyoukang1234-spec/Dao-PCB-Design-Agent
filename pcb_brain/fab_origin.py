#!/usr/bin/env python3
"""
fab_origin.py — 纯 Python 制造后端 (kicad_origin 桥)
====================================================

补足 pcb_predict 标出的认知误差: 当 kicad-cli 不在场时, 旧流水线只能写
"G04 Mock Gerber" 占位、跳过 DRC。但仓库里 `kicad_origin/engine` 是一套
零依赖纯 Python 的制造引擎 (Board.load → run_drc / write_gerber / write_excellon),
完全可以由 .kicad_pcb 直接产出**真实** Gerber/钻孔并跑 DRC。

于是无需安装 KiCad, 也能把"认知误差(看不见)"变成"真实观测(看得见)"。
本模块即是这座桥; 失败时返回 None, 让调用方继续走原有兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def available() -> bool:
    try:
        import kicad_origin.engine  # noqa: F401
        from kicad_origin.pcb.board import Board  # noqa: F401
        return True
    except Exception:
        return False


def origin_drc(pcb_path: str) -> Optional[Dict]:
    """用纯 Python 引擎跑真实 DRC。返回 None 表示引擎不可用。"""
    try:
        from kicad_origin.pcb.board import Board
        from kicad_origin.engine import run_drc
    except Exception:
        return None
    try:
        board = Board.load(pcb_path)
        rep = run_drc(board)
        return {
            "status": "kicad_origin",
            "violations": int(rep.error_count),
            "warnings": int(rep.warning_count),
            "passed": bool(rep.passed),
            "rules_run": list(rep.rules_run),
            "note": "纯 Python DRC (kicad_origin), 无需 KiCad",
        }
    except Exception as e:
        return {"status": "error", "violations": 0, "note": f"kicad_origin DRC 失败: {e}"}


def origin_gerber(pcb_path: str, gerber_dir: str) -> Optional[Dict]:
    """用纯 Python 引擎产出真实 Gerber + Excellon 钻孔。返回 None 表示不可用。"""
    try:
        from kicad_origin.pcb.board import Board
        from kicad_origin.engine import write_gerber, write_excellon
    except Exception:
        return None
    try:
        board = Board.load(pcb_path)
        Path(gerber_dir).mkdir(parents=True, exist_ok=True)
        files: List[str] = list(write_gerber(board, gerber_dir))
        drills: List[str] = list(write_excellon(board, gerber_dir))
        return {
            "status": "kicad_origin",
            "gerber_dir": gerber_dir,
            "file_count": len(files) + len(drills),
            "note": "真实 Gerber/Excellon (kicad_origin), 无需 KiCad",
        }
    except Exception as e:
        return {"status": "error", "gerber_dir": gerber_dir,
                "note": f"kicad_origin Gerber 失败: {e}"}
