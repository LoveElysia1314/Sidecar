import json

from dualign.gui.settings import (
    DualignConfig,
    KEY_ANOMALY_DETECTION,
)


def test_legacy_quality_gate_settings_are_discarded(tmp_path):
    path = tmp_path / "gui_config.json"
    path.write_text(
        json.dumps(
            {
                "quality_gate": {
                    "anchor_density_min": 0.75,
                    "gap_row_ratio_max": 0.03,
                    "zscore_k": 2.5,
                    "zscore_min_score": 0.55,
                }
            }
        ),
        encoding="utf-8",
    )
    config = DualignConfig()
    config._file_path = str(path)

    loaded = config.load()

    assert "quality_gate" not in loaded
    assert KEY_ANOMALY_DETECTION not in loaded
    config.save()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "quality_gate" not in persisted


def test_default_gui_settings_expose_no_alignment_gate_thresholds():
    defaults = DualignConfig.default_values()

    assert "quality_gate" not in defaults
    assert defaults[KEY_ANOMALY_DETECTION] == {
        "zscore_k": 3.0,
        "zscore_min_score": 0.6,
    }
