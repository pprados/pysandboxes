from pysandboxes.guard_envs import LearnEnviron
from pysandboxes.tools import set_is_in_sandbox


def test_environ() -> None:
    LearnEnviron._instance = None  # Reset singleton
    try:
        set_is_in_sandbox(True)
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
    finally:
        set_is_in_sandbox(False)
