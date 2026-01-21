from collections import namedtuple
from pathlib import Path
from typing import List, Dict, Tuple, NamedTuple

class ConfigLine(NamedTuple):
    rule:str
    path:Path
    ln:int

ConfigLines = List[ConfigLine]
Args = List[str]
Envs = Dict[str, str]
