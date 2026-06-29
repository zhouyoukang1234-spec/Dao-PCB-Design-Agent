"""Tests for stackup calculator."""
from dao_kicad.core.stackup import (
    standard_2layer, standard_4layer, standard_6layer,
    impedance_for_layer, solve_trace_width,
)


class TestStackup:
    def test_2layer(self):
        s = standard_2layer()
        assert len(s.copper_layers) == 2
        assert abs(s.total_thickness_mm - 1.6) < 0.01

    def test_4layer(self):
        s = standard_4layer()
        assert len(s.copper_layers) == 4
        assert abs(s.total_thickness_mm - 1.6) < 0.01

    def test_6layer(self):
        s = standard_6layer()
        assert len(s.copper_layers) == 6
        assert abs(s.total_thickness_mm - 1.6) < 0.01

    def test_summary(self):
        s = standard_4layer()
        text = s.summary()
        assert "4 copper layers" in text
        assert "F.Cu" in text


class TestImpedance:
    def test_microstrip_reasonable(self):
        s = standard_4layer()
        z = impedance_for_layer(s, "F.Cu", 0.2)
        assert 20 < z < 200

    def test_wider_trace_lower_z(self):
        s = standard_4layer()
        z_narrow = impedance_for_layer(s, "F.Cu", 0.1)
        z_wide = impedance_for_layer(s, "F.Cu", 0.5)
        assert z_wide < z_narrow

    def test_stripline(self):
        s = standard_6layer()
        z = impedance_for_layer(s, "In2.Cu", 0.15)
        assert 20 < z < 200

    def test_solve_50ohm(self):
        s = standard_4layer()
        w = solve_trace_width(s, "F.Cu", target_z0=50.0)
        assert 0.05 < w < 1.0
        z_check = impedance_for_layer(s, "F.Cu", w)
        assert abs(z_check - 50) < 2  # within 2Ω

    def test_solve_100ohm(self):
        s = standard_4layer()
        w = solve_trace_width(s, "F.Cu", target_z0=100.0)
        z_check = impedance_for_layer(s, "F.Cu", w)
        assert abs(z_check - 100) < 5
