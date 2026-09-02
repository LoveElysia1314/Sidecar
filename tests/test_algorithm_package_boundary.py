from pathlib import Path

import dualign
import dualign.core as core
from dualign.algorithms import MDLPipelineResult, align_mdl_pipeline


def test_mdl_pipeline_has_a_formal_algorithm_import_path():
    assert align_mdl_pipeline.__module__ == "dualign.algorithms.mdl.pipeline"
    assert MDLPipelineResult.__module__ == "dualign.algorithms.mdl.pipeline"


def test_production_packages_do_not_depend_on_experiments():
    package_root = Path(dualign.__file__).parent
    offenders = []
    for package_name in ("core", "services"):
        for path in (package_root / package_name).rglob("*.py"):
            if "dualign.experiments" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(package_root).as_posix())

    assert offenders == []


def test_production_alignment_facade_does_not_dispatch_to_legacy():
    facade = Path(core.__file__).with_name("aligner.py").read_text(encoding="utf-8")

    assert "legacy_anchor_aligner" not in facade
    assert not hasattr(core, "ALGORITHM_LEGACY_ANCHOR_V1")
