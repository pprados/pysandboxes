import threading
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
    assert envs._keys_used == set(), "The keys the code set itself need no rule"

    # Check singleton
    envs2 = LearnEnviron()
    assert envs == envs2


def test_iter_detection_environ() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    for k in envs:
        print(envs[k])

    assert not envs._keys_used, "Can not add key during iteration"
    assert not envs._scanned[threading.current_thread()]  # All key consumed


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


def test_key_read_after_a_scan_is_learned() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs["DEMO_API_KEY"] = "sk-demo"
    envs._written.discard("DEMO_API_KEY")  # As if the host had it before learning
    envs._keys_used.clear()

    def scan_proxies() -> None:  # What urllib.request.getproxies_environment() does before any request
        for name in envs:
            if name.lower().endswith("_proxy"):
                _ = envs[name]

    try:
        scan_proxies()
        _ = envs["DEMO_API_KEY"]
        assert "DEMO_API_KEY" in envs._keys_used, "A key skipped by an earlier scan must still be learned"
    finally:
        del envs["DEMO_API_KEY"]


def test_first_scanned_key_read_after_a_scan_is_learned() -> None:
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    first = next(iter(envs))  # A scan that stops at once reads nothing back
    for _ in envs:
        pass
    _ = envs[first]
    envs.commit_unsure()
    assert first in envs._keys_used, "A read in scan order that no read-back follows is a use"


def test_update_from_environ() -> None:
    d: dict[str, str] = {}
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    d.update(envs)
    assert not envs._keys_used
