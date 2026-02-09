from pathlib import Path
from typing import NamedTuple

from pysandboxes.config import CONFIG_NAME
from pysandboxes.guard_envs import EnvsRules
from pysandboxes.guard_files import FileRules
from pysandboxes.guard_import import ImportRules
from pysandboxes.guard_socket import SocketRules
from pysandboxes.sb_types import ConfigLines, Envs


class AllRules(NamedTuple):
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    use_py_sandbox: bool
    learning_path: Path
    learning: bool
    envs_rules: EnvsRules
    socket_rules: SocketRules
    file_rules: FileRules
    import_rules: ImportRules


EmptyRules = AllRules(
    config=(),
    envs=Envs({}),
    os_sandbox="subprocess",
    use_py_sandbox=False,
    learning_path=Path(CONFIG_NAME),
    learning=False,
    envs_rules=(),
    socket_rules=(),
    file_rules=(),
    import_rules=()
)
