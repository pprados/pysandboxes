import json
import os
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Empty
from typing import Optional, Callable, Awaitable, Any, Tuple, Iterator

from ipykernel.inprocess import InProcessKernelManager
from jupyter_client import KernelManager, BlockingKernelClient, KernelClient
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.localinterfaces import localhost
from jupyter_core.paths import jupyter_data_dir

from pysandboxes.executors.BasePythonExecutor import BasePythonExecutor


def _install_current_python_as_kernel(
        name: str,
        display_name: str,
        prefix: str = None
) -> None:
    """
    Installs the current Python interpreter as a Jupyter kernel.

    Args:
        name (str): The internal name of the kernel. This should be a simple,
                    slug-like string without spaces or special characters.
        display_name (str): The human-readable name that will appear in Jupyter's
                            kernel selection menus.
        prefix (str, optional): The directory where the kernel specification will be installed.
                                If None, it defaults to the user's Jupyter data directory.
                                This is useful for system-wide installations (requires root/admin)
                                or specific virtual environments.
    """
    # Determine the installation directory for the kernel spec
    if prefix:
        # Install to a specific prefix (e.g., a virtual environment's share/jupyter/kernels)
        kernel_dir = os.path.join(prefix, 'share', 'jupyter', 'kernels', name)
    else:
        # Default to the user's Jupyter data directory
        kernel_dir = os.path.join(jupyter_data_dir(), 'kernels', name)

    os.makedirs(kernel_dir, exist_ok=True)

    # Define the content of the kernel.json file
    # sys.executable points to the Python interpreter running this script
    kernel_spec_content = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": display_name,
        "language": "python"
    }

    # Write the kernel.json file
    kernel_json_path = os.path.join(kernel_dir, 'kernel.json')
    with open(kernel_json_path, 'w', encoding='utf-8') as f:
        json.dump(kernel_spec_content, f, indent=2)

    print(f"Kernel '{display_name}' installed successfully at: {kernel_dir}")
    print("Please ensure 'ipykernel' is installed in this Python environment:")
    print(f"    {sys.executable} -m pip install ipykernel")


def _check_kernel_exists(kernel_name: str) -> bool:
    """
    Checks if a Jupyter kernel with the given name is installed.

    Args:
        kernel_name (str): The internal name of the kernel (e.g., 'python3', 'my_dev_env').

    Returns:
        bool: True if the kernel exists, False otherwise.
    """
    ksm = KernelSpecManager()
    try:
        # get_kernel_spec will raise a NoSuchKernel exception if the kernel isn't found
        ksm.get_kernel_spec(kernel_name)
        return True
    except Exception:
        return False


def _start_new_kernel(
        in_process: bool,
        *,
        # FIXME: rendre paramétrable, S'assurer du stop des kernels
        startup_timeout: float = 2,
        shutdown_wait_time: float = 2,
        ip: str = localhost(),
        autorestart: bool = True,
        display_name:Optional[str] = None,
        **kwargs: Any
) -> Tuple[KernelManager, BlockingKernelClient]:
    """Start a new kernel, and return its Manager and Client"""
    # InProcessKernelManager est une piste pour forcer le sandbox
    assert "kernel_name" in kwargs, "kernel_name must be specified"
    if not _check_kernel_exists(kwargs["kernel_name"]):
        if not display_name:
            display_name = kwargs["kernel_name"]
        _install_current_python_as_kernel(
            kwargs["kernel_name"],
            display_name=display_name)

    # km = InProcessKernelManager(**kwargs) if in_process else KernelManager(**kwargs)
    km = InProcessKernelManager(**kwargs) if in_process else KernelManager()
    # TODO: le provisioner semble être le ctr des kernels
    km.shutdown_wait_time = shutdown_wait_time
    km.ip = ip
    km.autorestart = autorestart
    km.session.debug = True  # FIXME
    km.start_kernel()
    kc = km.client()
    kc.start_channels()
    try:
        # if not in_process:
        #     kc.wait_for_ready(timeout=startup_timeout)
        #     print("kernel ready")  # FIXME
        pass
    except RuntimeError as e:
        kc.shutdown()
        km.shutdown_kernel()
        raise
    return km, kc


@contextmanager
def _run_kernel(**kwargs: Any) -> Iterator[KernelClient]:
    """Context manager to create a kernel in a subprocess.

    The kernel is shut down when the context exits.

    Returns
    -------
    kernel_client: connected KernelClient instance
    """
    km, kc = _start_new_kernel(**kwargs)
    kc.session.debug = True
    try:
        yield kc
    finally:
        kc.stop_channels()
        kwargs = {}
        if not isinstance(km, InProcessKernelManager):
            kwargs = {"now": True}
        km.shutdown_kernel(**kwargs)


class IKernelExecutor(BasePythonExecutor):
    def __init__(self,
                 max_workers=None,
                 thread_name_prefix='',
                 initargs=(),
                 kernel_name='sandbox',
                 # kernel_name='python3',
                 ):
        super().__init__()
        self._tp = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
            initargs=initargs)
        self.kernel_name = kernel_name
        # TODO: in_process = True entraine que pas de kill possible
        self.in_process = True  # TODO: faire une sous-classe avec in_process=True

    # def shutdown(self):
    #     if self._km and self._km.is_alive():
    #         self._km.shutdown_kernel(now=True)
    #     self._km = None
    #
    # def __del__(self):
    #     self.shutdown()
    #
    # WARNING: Implémentation ou un kernel est lancé à chaque job.
    def call(self,
             code_action: str,
             tools: Optional[dict[str, Callable]] = None,
             timeout: Optional[int] = None) -> Any:
        def run():  # TODO: ajoute run timeout d'execution
            timeout = 120  # FIXME
            # TODO: faire une sériat
            json_code_action = f"""
import pickle
import base64
{code_action}
"""
            # json_code_action=code_action
            with _run_kernel(
                    in_process=self.in_process,  # FIXME
                    startup_timeout=timeout,
                    shutdown_wait_time=timeout,
                    ip=localhost(),
                    kernel_name=self.kernel_name,
                    autorestart=True,
            ) as kc:

                msg_id = kc.execute(json_code_action,
                                    # allow_stdin=False,
                                    # silent=True,  # BUG: silent=True ne fonctionne pas
                                    # C'est invoqué, mais cela ne remonte pas dans les messages
                                    # Je n'ai pas trouvé pourquoi. C'est pourtant envoyé
                                    user_expressions={
                                        "result":
                                            "base64.b64encode(pickle.dumps(_))"
                                    },
                                    )

                # 6. Boucle pour écouter les messages sur le canal iopub
                while True:
                    try:
                        # On attend un message du kernel (avec un timeout pour ne pas bloquer indéfiniment)
                        # kc.wait_for_ready()
                        msg = kc.get_iopub_msg(timeout=1)

                        # On vérifie que le message reçu est bien une réponse à notre requête
                        if msg['parent_header'].get('msg_id') == msg_id:
                            msg_type = msg['header']['msg_type']
                            content = msg['content']

                            print(f"{msg_type=} {content=}")
                            # On affiche les sorties de type 'print'
                            if msg_type == 'stream':
                                if content['name'] == 'stderr':
                                    print(
                                        f"[Sortie stderr] : {content['text'].strip()}",
                                        file=sys.stderr)
                                else:
                                    print(f"[Sortie Print] : {content['text'].strip()}")

                            # On affiche le résultat final de l'exécution
                            elif msg_type == 'error':
                                print(
                                    f"[ERROR] : {content['ename']} {content['evalue']}")
                                return None  # FIXME
                            elif msg_type == 'execute_result':
                                result = None
                                if "user_expressions" in content:
                                    print(f"********************* {content['user_expressions']}")
                                if "application/json" in content["data"]:
                                    result = content["data"]["application/json"][
                                        "result"]
                                elif "text/plain" in content["data"]:
                                    result = content["data"]["text/plain"]
                                print(f"[Résultat] : {result}")
                                return result

                            # On regarde l'état du kernel. S'il est 'idle', il a fini de travailler.
                            elif msg_type == 'status' and content[
                                'execution_state'] == 'idle':
                                print(
                                    "[Status] : Kernel inactif, l'exécution est terminée.")

                    except Empty:
                        print("EMPTY LOOP")  # Ignore
                        # return None  # FIXME
            return None  # FIXME: erreur

        return self._tp.submit(run)

    async def acall(self,
                    code_action: str,
                    tools: Optional[dict[str, Callable]] = None,
                    timeout: Optional[int] = None) -> Awaitable[Any]:
        pass
