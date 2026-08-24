from pathlib import Path

import dualign
import dualign.experiments as experiments
from dualign.algorithms import MDLPipelineResult, align_mdl_pipeline


def test_mdl_pipeline_has_a_formal_algorithm_import_path():
    assert align_mdl_pipeline.__module__ == "dualign.algorithms.mdl.pipeline"
    assert MDLPipelineResult.__module__ == "dualign.algorithms.mdl.pipeline"
    assert not hasattr(experiments, "align_mdl_pipeline")


def test_production_packages_do_not_depend_on_experiments():
    package_root = Path(dualign.__file__).parent
    offenders = []
    for package_name in ("core", "services"):
        for path in (package_root / package_name).rglob("*.py"):
            if "dualign.experiments" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(package_root).as_posix())

    assert offenders == []
