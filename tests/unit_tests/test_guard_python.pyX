from langgraph_codeagent.sandboxes.guard_python import restricted_python


def test_guard_python():
    result=restricted_python("print('hello world')")
    assert result == "_print = _print_(_getattr_)\n_print._call_print('hello world')"