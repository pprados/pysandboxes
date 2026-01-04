import os
import pathlib
import pytest
from io import open_code

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files


from test_guard_io import files

@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    deactivate_guard_files()


#%%
def test_pathlib_read_write_text(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    activate_guard_files(rules)
    from pathlib import Path
    (files["path"] / "to_write.txt").write_text("To write")
    assert Path(files["path"] / "to_write.txt").read_text() == "To write"
    (files["bind_dest"] / "to_write.txt").write_text("To write")
    assert Path(files["bind_dest"] / "to_write.txt").read_text() == "To write"


def test_pathlib_glob(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    activate_guard_files(rules)

    from pathlib import Path
    result = [Path(f).name for f in files['path'].glob("*")]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result
    result = [Path(f).name for f in files['bind_dest'].glob("*")]
    assert "bound_file.txt" in result


# TODO
# pathlib.Path.write_text = _wrap_filename(pathlib.Path.open)  # type: ignore
# pathlib.Path.write_bytes = _wrap_filename(pathlib.Path.open)  # type: ignore
# pathlib.Path.iterdir = _wrap_filename(pathlib.Path.open)  # type: ignore
# pathlib.Path.glob = _wrap_filename(pathlib.Path.open)  # type: ignore
# pathlib.Path.rglob = _wrap_filename(pathlib.Path.open)  # type: ignore
# pathlib.Path.walk = _wrap_filename(pathlib.Path.open)  # type: ignore


def test_pathlib_iterdir(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]
    activate_guard_files(rules)

    from pathlib import Path
    # with Path(files["visible"]).open(
    #         mode='r', buffering=-1, encoding=None,
    #         errors=None, newline=None) as f:
    #     assert f.read() == "Visible"
    #
    # assert Path(files["visible"]).read_text(
    #         encoding=None,
    #         errors=None) == "Visible"
    #
    # assert Path(files["visible"]).read_bytes() == str.encode("Visible")

    result = [f.name for f in Path(files['bind_dest']).iterdir()]
    assert "ignore.log" not in result
    assert "bound.txt" in result
    assert "visible.txt" in result

