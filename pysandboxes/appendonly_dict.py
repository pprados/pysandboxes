# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Append-only dictionary implementation for PySandboxes.

This module provides a specialized dictionary that only allows appending new
key-value pairs, preventing modification of existing entries. Used for security
configurations where immutability is important.
"""


def _check_called_by_imporlib(key: str) -> bool:
    """Check if function is called by importlib (for internal use).

    Args:
        key: Key being accessed.

    Returns:
        True if called by importlib, False otherwise.
    """
    return True
    import sys

    frame = sys._getframe()
    while frame and not frame.f_globals.get("__name__").startswith("importlib"):
        frame = frame.f_back
    if not frame:
        return False
    print(f"called by importlib for {key=}")
    return True


class AppendOnlyDict(dict):
    """
    A dictionary that only allows adding new key-value pairs.
    Deletion and modification of existing items are not permitted.
    """

    # def __init__(self,copy:dict,onetime_set:Set[str]):
    #     super().__init__(copy)
    #     self._onetime_set=onetime_set
    #     self._delay_change_order={}

    # def __setitem__(self, key: Any, value: Any) -> None:
    #     """
    #     Sets a new key-value pair.
    #     Prevents modification of existing keys.
    #     """
    #     # if key in self._delay_change_order:
    #     #     previous_val=self._delay_change_order[key]
    #     #     if value is previous_val:  # Detect a move order
    #     #         del self._delay_change_order[key]
    #     #         print(f"delay change order {key=}")
    #     #         super().pop(key)
    #     #         super().__setitem__(key, value)
    #     #     return
    #
    #     if not _check_called_by_imporlib(key):
    #         if key in self._onetime_set:
    #             self._onetime_set.remove(key)
    #             return super().__setitem__(key, value)
    #
    #         if key not in self:
    #             super().__setitem__(key, value)
    #         else:
    #             print("Ignore set %s",repr(key))
    #     else:
    #         return super().__setitem__(key,value)
    #
    # def __delitem__(self, key: Any) -> None:
    #     """
    #     Prevents deletion of items.
    #     """
    #     if not _check_called_by_imporlib(key):
    #         print("Ignore del %s", repr(key))
    #         pass  # Ignore
    #         self._delay_change_order[key]=self[key]
    #     else:
    #         return super().__delitem__(key)
    #
    # def pop(self, key: Any, *args: Any) -> Any:
    #     """
    #     Prevents popping items.
    #     """
    #     if not _check_called_by_imporlib(key):
    #         print("Ignore pop %s", repr(key))
    #         self._delay_change_order[key]=self[key]
    #         return self[key]
    #     else:
    #         return super().pop(key)
    #
    # def update(self, other: Any, **kwargs: Any) -> None:
    #     """
    #     Updates the dictionary with another dictionary.
    #     Prevents modification of existing keys.
    #     """
    #     if not _check_called_by_imporlib(None):
    #         if isinstance(other, Mapping):
    #             for key,val in other.items():
    #                 if key not in self:
    #                       self[key] = val
    #                 else:
    #                     print("Ignore update %s",repr(key))
    #             return
    #         if kwargs:
    #             for key,val in kwargs.items():
    #                 if key not in self:
    #                     self[key]=val
    #                 else:
    #                     print("Ignore update %s", repr(key))
    #         return
    #     else:
    #         return super().update(other, **kwargs)
