from collections import namedtuple
from pathlib import Path
from typing import List, Dict, Tuple, NamedTuple

from .immutable_dict import ImmutableDict


class ConfigLine(NamedTuple):
    rule:str
    path:Path
    ln:int

ConfigLines = List[ConfigLine]
Args = List[str]
Envs = ImmutableDict[str,str]
