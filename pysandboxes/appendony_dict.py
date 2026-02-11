import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

class AppendOnlyDict(dict):
    """
    A dictionary that only allows adding new key-value pairs.
    Deletion and modification of existing items are not permitted.
    """

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Sets a new key-value pair.
        Prevents modification of existing keys.
        """
        if key not in self:
            super().__setitem__(key, value)
        else:
            logger.debug("Ignore %s",repr(key))

    def __delitem__(self, key: Any) -> None:
        """
        Prevents deletion of items.
        """
        logger.debug("Ignore %s", repr(key))
        pass  # Ignore

    def pop(self, key: Any, *args: Any) -> Any:
        """
        Prevents popping items.
        """
        logger.debug("Ignore %s", repr(key))
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
                    logger.debug("Ignore %s",repr(key))
            return
        if kwargs:
            for key,val in kwargs.items():
                if key not in self:
                    self[key]=val
                else:
                    logger.debug("Ignore %s", repr(key))
        return
