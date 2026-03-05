"""Benchmarks for cache serialize/deserialize (export_brep / import_brep) speed.

Uses a screw part from bd_warehouse (https://github.com/gumyr/bd_warehouse)
for realistic geometry complexity.
"""
import pathlib

from bd_warehouse.thread import IsoThread
from build123d import Align
from build123d import Axis
from build123d import BuildPart
from build123d import Cylinder
from build123d import export_brep
from build123d import import_brep
from build123d import Mode
from build123d import Part


def make_top_screw(
    top_screw_height: float,
    top_screw_major_diameter: float,
    top_screw_pitch: float,
    top_screw_diameter_clearance: float,
    top_screw_ramp_clearance: float,
    top_screw_chamfer: bool,
    top_screw_chamfer_length: float,
    top_screw_chamfer_length2: float,
) -> Part:
    """Build a screw part for benchmark (bd_warehouse IsoThread + cylinder + optional chamfer)."""
    with BuildPart() as screw:
        thread = IsoThread(
            major_diameter=top_screw_major_diameter,
            pitch=top_screw_pitch,
            length=top_screw_height,
            external=True,
            hand="right",
            end_finishes=("raw", "chamfer"),
        )
        Cylinder(
            radius=thread.root_radius,
            height=thread.length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        if top_screw_chamfer:
            chamfer_cutter = Cylinder(
                radius=thread.major_diameter / 2,
                height=thread.length,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
                mode=Mode.PRIVATE,
            )
            screw.part = screw.part.intersect(
                chamfer_cutter.solid().chamfer(
                    length=top_screw_chamfer_length,
                    length2=top_screw_chamfer_length2,
                    edge_list=[chamfer_cutter.edges().sort_by(Axis.Z)[-1]],
                )
            )
    return screw.part


def test_benchmark_cache_serialize(benchmark, cache_folder: pathlib.Path) -> None:
    """Benchmark export_brep (cache serialize) speed."""
    part = make_top_screw(
        top_screw_height=10.0,
        top_screw_major_diameter=5.0,
        top_screw_pitch=1.0,
        top_screw_diameter_clearance=0.1,
        top_screw_ramp_clearance=0.1,
        top_screw_chamfer=True,
        top_screw_chamfer_length=0.5,
        top_screw_chamfer_length2=0.5,
    )
    path = cache_folder / "serialize_bench.brep"

    def _serialize() -> None:
        export_brep(part, str(path))

    benchmark(_serialize)
    assert path.is_file()


def test_benchmark_cache_deserialize(benchmark, cache_folder: pathlib.Path) -> None:
    """Benchmark import_brep (cache deserialize) speed."""
    path = cache_folder / "deserialize_bench.brep"
    part = make_top_screw(
        top_screw_height=10.0,
        top_screw_major_diameter=5.0,
        top_screw_pitch=1.0,
        top_screw_diameter_clearance=0.1,
        top_screw_ramp_clearance=0.1,
        top_screw_chamfer=True,
        top_screw_chamfer_length=0.5,
        top_screw_chamfer_length2=0.5,
    )
    export_brep(part, str(path))

    def _deserialize():
        return import_brep(path)

    result = benchmark(_deserialize)
    assert result is not None
