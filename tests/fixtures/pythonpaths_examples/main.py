from mr import artifact
from mypkg.main import ExampleBox


@artifact
def main():
    return ExampleBox()
