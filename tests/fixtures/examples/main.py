import os

from build123d import *
from mr import artifact
from mr.data_types import Result


class ExampleBox(BasePartObject):
    def __init__(
        self,
        box_width: float = 10 * MM,
        box_length: float = 10 * MM,
        box_height: float = 10 * MM,
        rotation: RotationLike = (0, 0, 0),
        align: Align | tuple[Align, Align, Align] | None = None,
        mode: Mode = Mode.ADD,
    ):
        self.box_width = box_width
        self.box_length = box_length
        self.box_height = box_height
        with BuildPart() as box:
            Box(self.box_width, self.box_length, self.box_height)
        super().__init__(box.part, rotation=rotation, align=align, mode=mode)


@artifact
def main():
    box = ExampleBox()
    return box


@artifact(sample=True)
def sample():
    box = ExampleBox()
    version = os.environ.get("MR_CI_BUILD_NUMBER", "0")

    # Default: no special versioning geometry when version string is empty
    versioned = box.part
    if version:
        # Engrave the version text slightly into the +X face of the box.
        text_height = box.box_height / 4
        inset = 0.2 * MM
        cut_depth = 0.5 * MM

        with BuildPart() as bp:
            add(box.part)
            # Sketch on a plane just inside the +X face.
            with BuildSketch(Plane.YZ.offset(box.box_width / 2 - inset)):
                Text(
                    str(version),
                    font_size=text_height,
                    align=(Align.CENTER, Align.CENTER),
                )
            extrude(-cut_depth, mode=Mode.SUBTRACT)

        versioned = bp.part

    return Result(model=box, versioned=versioned)
