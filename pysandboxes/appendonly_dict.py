import logging
from typing import Any, Mapping, Set


class AppendOnlyDict(dict):
    """
    A dictionary that only allows adding new key-value pairs.
    Deletion and modification of existing items are not permitted.
    """
    def __init__(self,copy:dict,onetime_set:Set[str]):
        super().__init__(copy)
        self._onetime_set=onetime_set

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Sets a new key-value pair.
        Prevents modification of existing keys.
        """
        if key in self._onetime_set:
            self._onetime_set.remove(key)
            return super().__setitem__(key, value)

        if key not in self:
            super().__setitem__(key, value)
        else:
            print("Ignore set %s",repr(key))

    def __delitem__(self, key: Any) -> None:
        """
        Prevents deletion of items.
        """
        print("Ignore del %s", repr(key))
        pass  # Ignore

    def pop(self, key: Any, *args: Any) -> Any:
        """
        Prevents popping items.
        """
        print("Ignore pop %s", repr(key))
        pass  # Ignore

    def update(self, other: Any, **kwargs: Any) -> None:
        """
        Updates the dictionary with another dictionary.
        Prevents modification of existing keys.
        """
        if isinstance(other, Mapping):
            for key,val in other.items():
                if key not in self:
                      self[key] = val
                else:
                    print("Ignore update %s",repr(key))
            return
        if kwargs:
            for key,val in kwargs.items():
                if key not in self:
                    self[key]=val
                else:
                    print("Ignore update %s", repr(key))
        return
