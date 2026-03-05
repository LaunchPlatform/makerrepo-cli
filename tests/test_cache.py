import pytest

from makerrepo_cli.cmds.shared.cache import make_cache_key


@pytest.mark.parametrize(
    "args, kwargs, expected",
    [
        (
            (),
            dict(foo="bar"),
            "16a4154f221f9a3733d9873f86166c18813865dfb432b9abeb841073fbd48cac",
        ),
        (
            ("hello", "baby"),
            dict(foo="bar"),
            "54169f0acbb76bd39c6003a8a3a881b2c0053d526f3da24e863691809164c926",
        ),
        (
            ("0", "0"),
            dict(),
            "d54c8c0586d78ae76e14b7247cb612a52e4375ef900bcfa1e3ed54d19fe79c63",
        ),
        (
            ("0", "1"),
            dict(),
            "e8339736d72712619602bc12ab193210075bf05535926f3bda7f58d39ba0a0ee",
        ),
        (
            (),
            dict(a="v0", b="v1"),
            "6d3c96b851c11544517c82df62bb33751f0fd80e0417ceb6259f5eb8f5cb8519",
        ),
        (
            (),
            dict(b="v1", a="v0"),
            "6d3c96b851c11544517c82df62bb33751f0fd80e0417ceb6259f5eb8f5cb8519",
        ),
    ],
)
def test_cache_key(args: tuple, kwargs: dict, expected: str):
    assert make_cache_key(args, kwargs) == expected
