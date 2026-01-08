from concurrent.futures import ThreadPoolExecutor
from queue import Queue

from pysandboxes.executors.exec_eval_stream import eval_stream, exec_stream


def test_eval_stream():
    assert eval_stream("1+2") == {"result": 1 + 2, "stderr": "",
                                  "stdout": ""}  # Without queue


def test_eval_stream_with_error():
    result = eval_stream("1/0")
    assert isinstance(result["exception"], ZeroDivisionError)
    result.pop("exception")
    assert (result ==
            {
                "stderr": "",
                "stdout": ""
            }
            )


def test_exec_stream():
    assert (exec_stream(
        "import sys;print('hello');print('error',file=sys.stderr)",
        globals_dict=globals(),
        locals_dict=locals()) == {
                "result": None,
                "stderr": "error\n",
                "stdout": "hello\n"})


def test_exec_stream_with_error():
    result = exec_stream(
        "import sys;print('hello');print('error',file=sys.stderr);10/0",
        globals_dict=globals(),
        locals_dict=locals())
    assert isinstance(result["exception"], ZeroDivisionError)
    result.pop("exception")
    assert (result == {
        "stderr": "error\n",
        "stdout": "hello\n"
    })

def test_eval_with_queue():
    with ThreadPoolExecutor(max_workers=10) as executor:
        stream_queue = Queue()
        code_string="1+2"
        fut = executor.submit(eval_stream,
                              code_string,
                              globals_dict=globals(),
                              locals_dict=locals(),
                              queue=stream_queue,
                              )
        step=0
        while True:
            msg = stream_queue.get()

            if "result" in msg:
                assert step == 0
                step += 1
                assert 3 == msg["result"]
                break
            elif "exception" in msg:
                assert False
            elif "stdout" in msg:
                assert False
            elif "stderr" in msg:
                assert False
        result = fut.result()
        assert result == {"result": 1 + 2, "stderr": "",
                                  "stdout": ""}

def test_exec_with_queue():
    with ThreadPoolExecutor(max_workers=10) as executor:
        stream_queue = Queue()
        code_string="import sys;print('hello');print('error',file=sys.stderr)"
        fut = executor.submit(exec_stream,
                              code_string,
                              globals_dict=globals(),
                              locals_dict=locals(),
                              queue=stream_queue,
                              )
        step=0
        while True:
            msg = stream_queue.get()

            if "result" in msg:
                assert step == 4
                step += 1
                assert None == msg["result"]
                break
            elif "exception" in msg:
                # assert step == 0
                # step += 1
                assert False
            elif "stdout" in msg:
                assert step in [0,1]
                assert step != 0 or "hello" == msg["stdout"]
                assert step != 1 or "\n" == msg["stdout"]
                step += 1

            elif "stderr" in msg:
                assert step in [2,3]
                assert step != 2 or "error" == msg["stderr"]
                assert step != 3 or "\n" == msg["stderr"]
                step += 1
        result = fut.result()
        assert (result == {
            "result": None,
            "stdout": "hello\n",
            "stderr": "error\n"})

def test_exec_with_queue_and_error():
    with ThreadPoolExecutor(max_workers=10) as executor:
        stream_queue = Queue()
        code_string="import sys;print('hello');print('error',file=sys.stderr); 10/0"
        fut = executor.submit(exec_stream,
                              code_string,
                              globals_dict=globals(),
                              locals_dict=locals(),
                              queue=stream_queue,
                              )
        step=0
        while True:
            msg = stream_queue.get()

            if "result" in msg:
                assert False
            elif "exception" in msg:
                assert step == 4
                step += 1
                assert isinstance(msg["exception"],ZeroDivisionError)
                break
            elif "stdout" in msg:
                assert step in [0,1]
                assert step != 0 or "hello" == msg["stdout"]
                assert step != 1 or "\n" == msg["stdout"]
                step += 1

            elif "stderr" in msg:
                assert step in [2,3]
                assert step != 2 or "error" == msg["stderr"]
                assert step != 3 or "\n" == msg["stderr"]
                step += 1
        result = fut.result()
        assert isinstance(result["exception"],ZeroDivisionError)
        result.pop("exception")
        assert (result == {
            "stdout": "hello\n",
            "stderr": "error\n"})
