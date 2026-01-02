from langgraph_codeagent.sandboxes.guard_python import run_in_guarded_python


def test_guard_python():
    result=run_in_guarded_python("print('hello world')")
    print(result)