from build123d import *
from mr import cached


@cached
def expensive_func(width: int, height: int, length: int):
    return Box(width, height, length)
