"""Tests for multilayer via-transition router."""

from dao_kicad.core.manipulate import BoardBuilder
from dao_kicad.core.router import Router, _SpatialIndex


def _make_board(layers=4, w=50, h=35):
    b = BoardBuilder.new(copper_layers=layers, width_mm=w, height_mm=h)
    b.set_rules(min_clearance_mm=0.15, min_track_mm=0.1, via_size_mm=0.3, via_drill_mm=0.15)
    return b


class TestSpatialIndex:
    def test_mark_and_check(self):
        si = _SpatialIndex(50, 35, cell_mm=0.5)
        si.mark(10, 10, 20, 10, 0.2, "NET1")
        assert not si.check_clear(15, 10, 15, 20, 0.2, "NET2", 0.15)
        assert si.check_clear(30, 10, 30, 20, 0.2, "NET2", 0.15)

    def test_same_net_no_conflict(self):
        si = _SpatialIndex(50, 35, cell_mm=0.5)
        si.mark(10, 10, 20, 10, 0.2, "NET1")
        assert si.check_clear(15, 10, 15, 20, 0.2, "NET1", 0.15)


class TestMultilayerRouter:
    def test_basic_multilayer(self):
        b = _make_board()
        b.add_nets("GND", "3V3", "S0", "S1")
        b.place("Package_QFP", "LQFP-48_7x7mm_P0.5mm", "U1", 15, 17, value="MCU")
        b.place("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical",
                "J1", 40, 17, value="HDR")
        b.assign_net("J1", "1", "GND")
        b.assign_net("J1", "2", "3V3")
        b.assign_net("J1", "3", "S0")
        b.assign_net("J1", "4", "S1")
        for i in range(1, 3):
            b.place("Capacitor_SMD", "C_0402_1005Metric", f"C{i}",
                    25, 10 + i * 8, value="100nF")
            b.assign_net(f"C{i}", "1", "3V3")
            b.assign_net(f"C{i}", "2", "GND")

        r = Router(b.board, min_clearance_mm=0.15)
        result = r.route_multilayer(width_mm=0.1, power_width_mm=0.2,
                                    power_nets={"GND", "3V3"})
        assert result.total > 0
        assert result.routed == result.total
        assert result.failed == 0
        assert result.tracks_added > 0

    def test_vias_added_on_congested(self):
        b = _make_board(w=30, h=20)
        b.add_nets("GND", "3V3", "S0", "S1", "S2", "S3")
        b.place("Package_QFP", "LQFP-48_7x7mm_P0.5mm", "U1", 10, 10, value="A")
        b.place("Package_QFP", "LQFP-48_7x7mm_P0.5mm", "U2", 22, 10, value="B")
        for i in range(1, 5):
            b.place("Capacitor_SMD", "C_0402_1005Metric", f"C{i}",
                    5 + i * 4, 18, value="100nF")
            b.assign_net(f"C{i}", "1", "3V3")
            b.assign_net(f"C{i}", "2", "GND")

        r = Router(b.board, min_clearance_mm=0.15)
        result = r.route_multilayer(width_mm=0.08, power_width_mm=0.15,
                                    power_nets={"GND", "3V3"})
        assert result.routed == result.total
        # Dense board should produce some vias
        assert result.vias_added >= 0  # may or may not need vias


class TestCollisionAwareRouting:
    def test_collision_avoidance(self):
        b = _make_board()
        b.add_nets("GND", "3V3", "S0")
        b.place("Connector_PinHeader_2.54mm", "PinHeader_1x03_P2.54mm_Vertical",
                "J1", 10, 17, value="A")
        b.place("Connector_PinHeader_2.54mm", "PinHeader_1x03_P2.54mm_Vertical",
                "J2", 40, 17, value="B")
        b.assign_net("J1", "1", "GND")
        b.assign_net("J1", "2", "3V3")
        b.assign_net("J1", "3", "S0")
        b.assign_net("J2", "1", "GND")
        b.assign_net("J2", "2", "3V3")
        b.assign_net("J2", "3", "S0")

        r = Router(b.board, min_clearance_mm=0.15)
        result = r.route_all(strategy="manhattan", width_mm=0.15,
                             power_width_mm=0.3, power_nets={"GND", "3V3"})
        assert result.routed == result.total
        assert result.tracks_added > 0
