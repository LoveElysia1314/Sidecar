"""Version metadata consistency tests."""

from importlib.metadata import version

from dualign import __version__
from dualign.core import ALIGN_CACHE_REVISION, ALIGN_CORE_VERSION


def test_runtime_version_comes_from_package_metadata():
    assert __version__ == version("dualign")
    assert ALIGN_CORE_VERSION == ALIGN_CACHE_REVISION
