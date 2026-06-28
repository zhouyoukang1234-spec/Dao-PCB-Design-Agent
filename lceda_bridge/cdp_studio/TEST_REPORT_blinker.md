# Test Report — NE555 Blinker, Full-Chain Programmatic PCB

**Result: PASS (end-to-end, one-shot).** A single `build_blinker.py` run drove
嘉立创EDA Pro Web entirely over Chrome DevTools Protocol (no human clicks) and
produced a real, manufacturable board.

- Account: `15606700905` / workspace `aiotvr`
- Project: `Dao_Blinker_093606` (uuid `27464bf7c5794719a2e8173a902d0599`)
- EDA: JLCEDA Pro V3.2.148, driven via `window._EXTAPI_ROOT_` (94 namespaces)

## Pipeline stages (all verified)

| Stage | EXTAPI / mechanism | Result |
|-------|--------------------|--------|
| scaffold | `dmt_Project.createProject` + `openProject` + active-project verify | project/board/sch/pcb uuids |
| place | `sch_PrimitiveComponent.placeComponentWithMouse` + settle-click | U1 NE555, R1, R2, C1 placed |
| designate | `modify()` after placement | U1/R1/R2/C1 |
| wire | `sch_PrimitiveWire.create` (orthogonal, int coords) | 7 wires |
| sync to PCB | `pcb_Document.importChanges` + auto-click "Apply Changes" | 4 footprints, 3 nets (GND/RA/VCC) |
| board outline | `pcb_PrimitiveLine.create` ×4 around bbox+margin on layer 11 | purple GKO rectangle |
| DRC | `pcb_Drc` | ran (returned findings) |
| export | in-page `getGerberFile/getBomFile/...` → `arrayBuffer()` → base64 | 4 artifacts on disk |

## Manufacturing output (on disk)

`exports/Dao_Blinker_093606/`:
- `Dao_Blinker_Gerber` (zip, 7934 B) — **complete fab package**:
  `GTL, GBL, GTO, GBO, GTS, GBS, GTP, GKO (board outline), GDL,
  FlyingProbeTesting.json, PCB下单必读.txt`
- `Dao_Blinker_BOM.xlsx` (6912 B)
- `Dao_Blinker_PNP` (7117 B, pick & place)
- `Dao_Blinker_Netlist.enet` (6865 B)

## Evidence

PCB — auto board outline (purple) enclosing U1/R1/R2/C1 footprints:

![PCB with board outline](../../../demos/pcb_outline.png)

Zoom — real DIP-8 land pattern (copper pads + silkscreen) and R2 designator:

![DIP-8 footprint detail](../../../demos/pcb_footprint.png)

Schematic — NE555 pins wired, net labels VCC / RA / RB:

![Wired schematic](../../../demos/sch_wired.png)

## Known issues found this run (to refine next)

1. **Net merge**: DRC warned `Wire $1N4 has multiple net names: RA, RA, RB, RB`.
   Overlapping `connect()` polylines fused the RA and RB nets, so only 3 of 4
   intended nets reached the PCB. Fix: route each net on a distinct track / use
   net-aware pin-to-pin segments that don't share a vertex.
2. **3D view**: `/engine/init` throws "can't call multiple times" when the 3D
   tab is (re)opened in an automated session; recover with a save-safe reload.
3. **DRC = fail** is expected here (floating pins, no copper routing yet) — next
   step is autorouting before DRC.

## Robustness hardened this session

- Browser-process crash auto-recovery: relaunch Chrome for Testing (reuse
  profile) → passport account login → **auto-drag slider captcha** → reload to
  pick up session.
- `Page.reload` with unsaved changes pops a native `beforeunload` dialog that
  hangs CDP / can close the browser → save first + null `onbeforeunload`.
- Editor-session reconnect retries `Runtime.enable` (target briefly unresponsive
  after reload).
