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


def test_a_key_read_after_the_scan_moved_past_it_is_still_learned() -> None:
    """A read must match the scan's last entry exactly: nothing merely ``>`` or ``<`` it, in
    whatever lexical order, may be mistaken for that entry's own read-back."""
    envs = LearnEnviron()  # Reset singleton
    envs["ZZZ_TEST_KEY"] = "z"
    envs._written.discard("ZZZ_TEST_KEY")
    envs._keys_used.clear()
    t = threading.current_thread()
    envs._scanned[t] = ["AAA_TEST_KEY"]  # Lexically below the key we are about to read
    envs._yielded[t] = "ZZZ_TEST_KEY"  # Matches the key, not the pending scan entry
    try:
        _ = envs["ZZZ_TEST_KEY"]
        assert "ZZZ_TEST_KEY" in envs._keys_used, "An unrelated read must still be learned"
    finally:
        del envs["ZZZ_TEST_KEY"]
        envs._scanned.pop(t, None)
        envs._yielded.pop(t, None)


def test_a_key_read_before_the_scan_entry_is_still_learned() -> None:
    """Same as above, with the key sorting the other way: the comparison must not be ordering-based."""
    envs = LearnEnviron()  # Reset singleton
    envs["AAA_TEST_KEY"] = "a"
    envs._written.discard("AAA_TEST_KEY")
    envs._keys_used.clear()
    t = threading.current_thread()
    envs._scanned[t] = ["ZZZ_TEST_KEY"]  # Lexically above the key we are about to read
    envs._yielded[t] = "AAA_TEST_KEY"
    try:
        _ = envs["AAA_TEST_KEY"]
        assert "AAA_TEST_KEY" in envs._keys_used, "An unrelated read must still be learned"
    finally:
        del envs["AAA_TEST_KEY"]
        envs._scanned.pop(t, None)
        envs._yielded.pop(t, None)


def test_a_reconstructed_equal_key_still_matches_the_scan_by_value() -> None:
    """The scan-detection comparisons must use ``==``, not ``is``: a key rebuilt at runtime, equal
    in content to the scanned and yielded keys but never interned to the same object, is still
    recognised as their own read-back."""
    envs = LearnEnviron()  # Reset singleton
    envs["DEMO_API_KEY"] = "sk-demo"
    envs._written.discard("DEMO_API_KEY")
    envs._keys_used.clear()
    t = threading.current_thread()
    base = "DEMO_API_KEY"
    scanned_key = (base + "_")[:-1]
    yielded_key = (base + "_")[:-1]
    assert scanned_key is not base and yielded_key is not base and scanned_key is not yielded_key
    envs._scanned[t] = [scanned_key]
    envs._yielded[t] = yielded_key
    try:
        _ = envs[base]
        assert "DEMO_API_KEY" not in envs._keys_used, "A scan's own read-back must not be learned"
        assert not envs._scanned[t], "The matched key must be popped from the pending scan"
        assert "DEMO_API_KEY" not in envs._unsure.get(t, []), "A confirmed read-back is not merely 'unsure'"
    finally:
        del envs["DEMO_API_KEY"]
        envs._scanned.pop(t, None)
        envs._yielded.pop(t, None)
        envs._unsure.pop(t, None)


def test_a_reconstructed_equal_key_is_not_mistaken_when_another_entry_remains() -> None:
    """With more than one pending scan entry, a non-identical-but-equal match on the scan's last
    entry must still take the "read back the scan" branch, not the "unrelated read" one: a single
    remaining entry masks this, because that branch also empties and discards ``_unsure``."""
    envs = LearnEnviron()  # Reset singleton
    envs["DEMO_API_KEY"] = "sk-demo"
    envs._written.discard("DEMO_API_KEY")
    envs._keys_used.clear()
    t = threading.current_thread()
    base = "DEMO_API_KEY"
    scanned_key = (base + "_")[:-1]
    yielded_key = (base + "_")[:-1]
    assert scanned_key is not base and yielded_key is not base
    envs._scanned[t] = ["AAA_OTHER_KEY", scanned_key]
    envs._yielded[t] = yielded_key
    try:
        _ = envs[base]
        assert "DEMO_API_KEY" not in envs._keys_used, "A scan's own read-back must not be learned"
        assert envs._scanned[t] == ["AAA_OTHER_KEY"], "Only the matched, last entry is popped"
    finally:
        del envs["DEMO_API_KEY"]
        envs._scanned.pop(t, None)
        envs._yielded.pop(t, None)
        envs._unsure.pop(t, None)


def test_a_key_before_the_remaining_scan_head_is_not_mistaken_for_it() -> None:
    """A read sorting lexically before the scan's remaining head must not be mistaken for it."""
    envs = LearnEnviron()  # Reset singleton
    envs["AAA_TEST_KEY"] = "a"
    envs._written.discard("AAA_TEST_KEY")
    envs._keys_used.clear()
    t = threading.current_thread()
    envs._scanned[t] = ["ZZZ_TEST_KEY"]
    envs._yielded.pop(t, None)
    try:
        _ = envs["AAA_TEST_KEY"]
        assert "AAA_TEST_KEY" in envs._keys_used, "An unrelated read must still be learned"
    finally:
        del envs["AAA_TEST_KEY"]
        envs._scanned.pop(t, None)


def test_update_from_environ() -> None:
    d: dict[str, str] = {}
    envs = LearnEnviron()  # Reset singleton
    envs._keys_used.clear()
    d.update(envs)
    assert not envs._keys_used
