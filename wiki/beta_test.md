# Beta-test

Read all the documentation and test the project with small demos.

This project is currently under development. It is neither stable nor [finished](roadmap.md). A first major step has been achieved: **patching all APIs that provide file and network access.**

# 1. Check usage
These APIs are sensitive. A small error in the patch will cause a program to crash, even if it runs fine without sandbox activation. It is crucial to ensure that applications run without any changes when invoked with **`python-sb`**.

You can help us with this by participating in the beta tests. Here is how you can proceed:

1.  Go to your project directory.
2.  Activate the corresponding virtual environment (`source .venv/activate` or equivalent).
3.  Install **Py-sandboxes**:
    ```bash
    pip install git+https://github.com/pprados/pysandboxes.git
    ```
4.  Modify the launch command of your program, which should be something like `python ...`, to **`python-sb --learn ...`**.
    This launches your program in **learning mode**. Ideally, you should not notice any degradation in your application's performance. At the end of its execution, a **`.py-sandboxes`** file will be populated with the different privileges observed during the run.
   You can continue with different scenario of usages.
5.  Check this file to ensure that the proposed rules appear consistent with your program. Adjust them if necessary and continue in learning mode.
6.  If you do not encounter any errors, you can then switch to **protected mode**. To do this, invoke your program with **`python-sb ...`**. Ideally, your program should not be degraded. If security alerts or exceptions are triggered, modify the settings file accordingly, and continue until the configuration is stable.
7.  In case of an issue, depending on your ability:
    1.  Retrieve the **complete stack trace**. This will allow me to identify the patched function causing the problem. Open a ticket with this information.
    2.  Try to identify the cause of the problem yourself and open a ticket with your analysis.
    3.  Fix the problem and propose a pull request.

# 2. Add demo
You can produce others `./samples` for different frameworks and use **py-sandboxes**
