from pathlib import Path
from typing import NamedTuple, Optional

from pysandboxes.guard_envs import EnvsRules
from pysandboxes.guard_files import FileRules
from pysandboxes.guard_import import ImportRules
from pysandboxes.guard_socket import SocketRules
from pysandboxes.types import ConfigLines, Envs


class AllRules(NamedTuple):
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    use_py_sandbox: bool
    learning_path: Optional[Path]
    envs_rules: EnvsRules
    socket_rules: SocketRules
    file_rules: FileRules
    import_rules: ImportRules
