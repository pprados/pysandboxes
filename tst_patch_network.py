import os
from typing import Tuple, Any, Optional, Iterable
from typing_extensions import Buffer

if True:
    print("******** Before import _socket")
    import _socket
    print("******** after import _socket")


    import socket
    class Guard_socket(socket.socket):
        # __slots__ = ["__weakref__", "_io_refs", "_closed"]

        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
            super().__init__(family,type,proto,fileno)

        def bind(self, address:Tuple) -> None:
            super().bind(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def connect(self, address:Tuple) -> None:  # real signature unknown; restored from __doc__
            print("*** hack socket connect")
            super().connect(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def connect_ex(self, address:Tuple) -> int:  # real signature unknown; restored from __doc__
            print("*** hack socket connect_ex")
            super().connect_ex(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def listen(self, backlog:Optional[int]=None) -> None:  # real signature unknown; restored from __doc__
            super().listen(backlog)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def accept(self) -> tuple[socket,Any]:
            return super().accept()

    socket.socket=Guard_socket
    print("******** Guard socket activated")
#%% Step 3, use it
from fake_tools import Fake_tools

tools=Fake_tools()
print("---- load socket")
tools.load_socket()
print("---- load request")
tools.load_request()
print("---- load urlopen")
tools.load_urlopen()
