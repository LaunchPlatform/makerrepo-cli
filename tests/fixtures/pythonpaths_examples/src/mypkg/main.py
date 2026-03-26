from build123d import Align
from build123d import BasePartObject
from build123d import Box
from build123d import BuildPart
from build123d import MM
from build123d import Mode
from build123d import RotationLike


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
