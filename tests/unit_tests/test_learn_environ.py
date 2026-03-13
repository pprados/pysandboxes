from typing import Iterator

from pysandboxes.guard_envs import LearnEnviron


def test_environ() -> None:
    LearnEnviron._instance = None  # Reset singleton
    envs = LearnEnviron()

    assert "not_present" not in envs
    envs["key"] = "value"
    envs["key2"] = "value2"
    assert "key" in envs
    assert envs["key"] == "value"
    assert envs["key2"] == "value2"

    assert envs.get("not_present") is None
    assert envs.get("key") == "value"
    del envs["key"]
    assert envs.get("key") is None

    assert envs._get("notrace") is None
    assert envs._keys_used == {"key", "key2"}

    # Check singleton
    envs2 = LearnEnviron()
    assert envs == envs2


def test_iter_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for k in envs:
        print(envs[k])

    assert not envs._keys_used, "Can not add key during iteration"
    assert not len(next(iter(envs._ignore_keys.items()))[1][1])  # All key consumed


def test_iter_use_by_child_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()

    def use_key(envs: LearnEnviron, k: str) -> None:
        print(envs[k])

    for k in envs:
        use_key(envs, k)
    assert not envs._keys_used, "Can add key during iteration, used by a child frame"


def test_iter_use_by_brother_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()

    def use_key(envs: LearnEnviron) -> Iterator[str]:
        for k in envs:
            yield k

    for k in use_key(envs):
        print(envs[k])
    assert not envs._keys_used, "Can add key during iteration"


def test_for_comprenhension_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    _ = {k: v for k, v in envs.items()}
    assert not envs._keys_used, "Can not add key during iteration"


def test_iter_items_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for _ in envs.items():
        pass
    assert not envs._keys_used, "Can not add key during iteration"


def test_iter_keys_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for k in envs.keys():
        _ = envs[k]
    assert not envs._keys_used, "Can not add key during iteration"


def test_iter_values_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for _ in envs.values():
        pass
    assert not envs._keys_used, "Can not add key during iteration"


def test_iter_use_directly_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for k in envs.keys():
        _ = envs[k]
        _ = envs["PATH"]
    assert "PATH" in envs._keys_used, "Can add direct key usage during iteration"


def test_update_from_environ() -> None:
    d: dict[str, str] = {}
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    d.update(envs)
    assert not envs._keys_used
