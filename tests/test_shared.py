"""Tests for makerrepo_cli.cmds.shared (list output format, item_to_list_payload)."""
import pathlib

from makerrepo_cli.cmds.shared.utils import item_to_list_payload
from makerrepo_cli.cmds.shared.utils import ListOutputFormat


class TestListOutputFormat:
    def test_json_value(self) -> None:
        assert ListOutputFormat.JSON.value == "json"

    def test_enum_members(self) -> None:
        assert list(ListOutputFormat) == [ListOutputFormat.JSON]


class TestItemToListPayload:
    def test_includes_module_and_name(self) -> None:
        class Item:
            pass

        payload = item_to_list_payload(Item(), "my_module", "my_name")
        assert payload["module"] == "my_module"
        assert payload["name"] == "my_name"

    def test_includes_scalar_attributes(self) -> None:
        class Item:
            sample = "a box"
            filename = "/path/to/file.py"
            lineno = 10

        payload = item_to_list_payload(Item(), "m", "n")
        assert payload["sample"] == "a box"
        assert payload["filename"] == "/path/to/file.py"
        assert payload["lineno"] == 10

    def test_includes_path_as_string(self) -> None:
        class Item:
            file_path = pathlib.Path("/abs/path/to/module.py")

        payload = item_to_list_payload(Item(), "m", "n")
        assert payload["file_path"] == "/abs/path/to/module.py"

    def test_excludes_callables(self) -> None:
        class Item:
            name = "x"
            func = lambda self: None  # noqa: E731

        payload = item_to_list_payload(Item(), "m", "n")
        assert "func" not in payload
        assert payload["name"] == "n"  # overwritten by args

    def test_excludes_private_attributes(self) -> None:
        class Item:
            name = "x"
            _private = "hidden"

        payload = item_to_list_payload(Item(), "m", "n")
        assert "_private" not in payload

    def test_sample_fallback_when_non_scalar(self) -> None:
        class NonStrSample:
            sample = object()  # not str/int/float/bool/Path

        payload = item_to_list_payload(NonStrSample(), "m", "n")
        assert "sample" in payload
        assert isinstance(payload["sample"], str)

    def test_registry_module_name_override_item_attrs(self) -> None:
        class Item:
            module = "other_mod"
            name = "other_name"

        payload = item_to_list_payload(Item(), "registry_module", "registry_name")
        assert payload["module"] == "registry_module"
        assert payload["name"] == "registry_name"
