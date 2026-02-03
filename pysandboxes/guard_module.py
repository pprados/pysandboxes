import types
from typing import Any


def readonly_module(name: str):
    import sys
    module = sys.modules[name]

    class ModuleAttributeController(types.ModuleType):
        """
        A custom class that acts as a module and controls attribute access.
        """

        def __init__(self):
            super().__init__(module.__name__)

        def __setattr__(self, name: str, value: Any) -> None:
            """
            Intercepts all attribute assignments to the module.
            """
            if not name.startswith("_"):
                module.__setattr__(name, value)
                return
            raise AttributeError(f"'{name}' is read-only")

        def __getattr__(self, name: str) -> Any:
            """
            Intercepts all attribute accesses to the module.
            """
            if not name.startswith("_"):
                return module.__dict__[name]
            raise AttributeError(f"module '{name}' has no attribute '{name}'")

    sys.modules[name] = ModuleAttributeController()
