import os
from typing import Tuple, Any, Optional, Iterable
from typing_extensions import Buffer

if True:
    print("******** Before import _socket")
    import _socket
    print("******** after import _socket")


    class GuardSocketType(_socket.SocketType):
        def __init__(self,family, type, proto, fileno):
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")
            # super().__init__(family, type, proto, fileno)
            self.family=family
            self.type=type
            self.proto=proto
            self._io_refs=fileno  # FIXME?
            print("GuardSocketType.__init__()")

        def bind(self, address):
            super().bind(address)
            raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def close(self):  # real signature unknown; restored from __doc__
        #     # super().close()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #     pass

        def connect(self, address):  # real signature unknown; restored from __doc__
            super().connect(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def connect_ex(self, address):  # real signature unknown; restored from __doc__
            super().connect_ex(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def detach(self):  # real signature unknown; restored from __doc__
            super().detach()
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def fileno(self):  # real signature unknown; restored from __doc__
            return super().fileno()
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def getblocking(self):  # real signature unknown; restored from __doc__
        #     return super().getblocking()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getpeername(self):  # real signature unknown; restored from __doc__
        #     return super().getpeername()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getsockname(self):  # real signature unknown; restored from __doc__
        #     return super().getsockname()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getsockopt(self, level, option,
        #                buffersize=None):  # real signature unknown; restored from __doc__
        #     return super().getsockop(level,buffersize)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def gettimeout(self):  # real signature unknown; restored from __doc__
        #     return super().gettimeout()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def listen(self, backlog=None):  # real signature unknown; restored from __doc__
            return super().listen(backlog)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def recv(self, buffersize,
        #          flags=None):  # real signature unknown; restored from __doc__
        #     return super().rec(buffersize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvfrom(self, buffersize,
        #              flags=None):  # real signature unknown; restored from __doc__
        #     return super().recvfrom(buffersize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvfrom_into(self, buffer, nbytes=None,
        #                   flags=None):  # real signature unknown; restored from __doc__
        #     return super().recvfrom_into(buffer,nbytes,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvmsg(self, bufsize, ancbufsize=None,
        #             flags=None):  # real signature unknown; restored from __doc__
        #     return super().recvmsg(bufsize,ancbufsize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvmsg_into(self, buffers, ancbufsize=None,
        #                  flags=None):  # real signature unknown; restored from __doc__
        #     return super().recvmsg_into(buffers,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def recv_into(self, buffer, nbytes=None,
        #               flags=None):  # real signature unknown; restored from __doc__
        #     return super().recv_into(buffer,nbytes,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def send(self, data, flags=None):  # real signature unknown; restored from __doc__
        #     return super().send(data,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendall(self, data,
        #             flags=None):  # real signature unknown; restored from __doc__
        #     return super().sendall(data,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendmsg(self, buffers, ancdata=None, flags=None,
        #             address=None):  # real signature unknown; restored from __doc__
        #     return super().sendmsg(buffers,ancdata,flags,address)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendmsg_afalg(self, msg=None, *args,
        #                   **kwargs):  # real signature unknown; NOTE: unreliably restored from __doc__
        #     return super().sendmsg_afalg(msg,*args,**kwargs)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendto(self, data, flags=None, *args,
        #            **kwargs):  # real signature unknown; NOTE: unreliably restored from __doc__
        #     return super().sendto(data,flags,*args,**kwargs)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def setblocking(self, flag):  # real signature unknown; restored from __doc__
        #     return super().setblocking(flag)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def setsockopt(self, level, option,
        #                value):  # real signature unknown; restored from __doc__
        #     return super().setsockopt(level,option,value)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def settimeout(self, timeout):  # real signature unknown; restored from __doc__
        #     super().settimeout(timeout)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def shutdown(self, flag):  # real signature unknown; restored from __doc__
        #     super().shutdown(flag)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")


    # _socket.socket = GuardSocketType

    print("******** Before import socket")
    import socket
    class Guard_socket(socket.socket):
        # __slots__ = ["__weakref__", "_io_refs", "_closed"]

        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
            super().__init__(family,type,proto,fileno)

        def bind(self, address:Tuple) -> None:
            super().bind(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def close(self) -> None:  # real signature unknown; restored from __doc__
        #     # super().close()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #     pass

        def connect(self, address:Tuple) -> None:  # real signature unknown; restored from __doc__
            print("*** hack socket connect")
            super().connect(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def connect_ex(self, address:Tuple) -> int:  # real signature unknown; restored from __doc__
            print("*** hack socket connect_ex")
            super().connect_ex(address)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def detach(self) -> int:  # real signature unknown; restored from __doc__
        #     super().detach()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def fileno(self) -> int:  # real signature unknown; restored from __doc__
        #     return super().fileno()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def getblocking(self) -> bool:  # real signature unknown; restored from __doc__
        #     return super().getblocking()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getpeername(self) -> Any:  # real signature unknown; restored from __doc__
        #     return super().getpeername()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getsockname(self) -> Any:  # real signature unknown; restored from __doc__
        #     return super().getsockname()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def getsockopt(self,
        #                level:Any,
        #                option:Any,
        #                buffersize:Optional[int]=None) -> None:  # real signature unknown; restored from __doc__
        #     return super().getsockopt(level,option, buffersize)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def gettimeout(self) -> Optional[float]:  # real signature unknown; restored from __doc__
        #     return super().gettimeout()
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        def listen(self, backlog:Optional[int]=None) -> None:  # real signature unknown; restored from __doc__
            super().listen(backlog)
            # raise RuntimeError("Accès réseau interdit : appel bloqué.")

        # def recv(self,
        #          buffersize:Any,
        #          flags:Optional[int]=None) -> bytes:  # real signature unknown; restored from __doc__
        #     return super().rec(buffersize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvfrom(self,
        #              buffersize:Any,
        #              flags:Optional[int]=None) -> Tuple[bytes,Any]:  # real signature unknown; restored from __doc__
        #     return super().recvfrom(buffersize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvfrom_into(self,
        #                   buffer:Buffer,
        #                   nbytes:Optional[int]=None,
        #                   flags:Optional[int]=None) -> Tuple[int,Any]:  # real signature unknown; restored from __doc__
        #     return super().recvfrom_into(buffer,nbytes,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvmsg(self,
        #             bufsize:int,
        #             ancbufsize:Optional[int]=None,
        #             flags:Optional[int]=None) ->  tuple[bytes, list[tuple[int, int, bytes]], int, Any]:  # real signature unknown; restored from __doc__
        #     return super().recvmsg(bufsize,ancbufsize,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def recvmsg_into(self,
        #                  buffers:Iterable[Buffer],
        #                  ancbufsize:Optional[int]=None,
        #                  flags:Optional[int]=None) -> tuple[int, list[tuple[int, int, bytes]], int, Any]:  # real signature unknown; restored from __doc__
        #     return super().recvmsg_into(buffers,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def recv_into(self,
        #               buffer:Buffer,
        #               nbytes:Optional[int]=None,
        #               flags:Optional[int]=None) -> int:  # real signature unknown; restored from __doc__
        #     return super().recv_into(buffer,nbytes,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def send(self,
        #          data:Buffer,
        #          flags:Optional[int]=None) -> int:  # real signature unknown; restored from __doc__
        #     return super().send(data,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendall(self,
        #             data:Buffer,
        #             flags:Optional[int]=None) -> None:  # real signature unknown; restored from __doc__
        #     super().sendall(data,flags)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendmsg(self,
        #             buffers:Iterable[Buffer],
        #             ancdata:Iterable[tuple[int,int,Buffer]]=None,
        #             flags:Optional[int]=None,
        #             address:Tuple[Any,...]=None) -> int:  # real signature unknown; restored from __doc__
        #     return super().sendmsg(buffers,ancdata,flags,address)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendmsg_afalg(self,
        #                   msg:Optional[Iterable[Buffer]]=None,
        #                   *args:Any,
        #                   **kwargs:Any) -> int:  # real signature unknown; NOTE: unreliably restored from __doc__
        #     return super().sendmsg_afalg(msg,*args,**kwargs)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def sendto(self,
        #            data:Any,
        #            flags:Optional[int]=None,
        #            *args:Any,
        #            **kwargs:Any):  # real signature unknown; NOTE: unreliably restored from __doc__
        #     return super().sendto(data,flags,*args,**kwargs)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")


        # def setblocking(self, flag):  # real signature unknown; restored from __doc__
        #     return super().setblocking(flag)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        #
        # def setsockopt(self, level, option,
        #                value):  # real signature unknown; restored from __doc__
        #     return super().setsockopt(level,option,value)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def settimeout(self, timeout):  # real signature unknown; restored from __doc__
        #     super().settimeout(timeout)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")
        #
        # def shutdown(self, flag):  # real signature unknown; restored from __doc__
        #     super().shutdown(flag)
        #     # raise RuntimeError("Accès réseau interdit : appel bloqué.")


#----------------------
        # def __enter__(self):
        #     return super().__enter__()
        #
        # def __exit__(self, *args):
        #     super().__exit__()
        #
        # def __repr__(self):
        #     return super().__repr__()
        #
        # def __getstate__(self):
        #     raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

        # def dup(self):f
        #     return super().dup()

        def accept(self) -> tuple[socket,Any]:
            return super().accept()

        # def makefile(self, mode="r", buffering=None, *,
        #              encoding=None, errors=None, newline=None):
        #     return super().makefile(mode,buffering,encoding,errors,newline)

        # if hasattr(os, 'sendfile'):
        #
        #     def _sendfile_use_sendfile(self, file, offset=0, count=None):
        #         return super()._sendfile_use_sendfile(file,offset,count)
        # else:
        #     def _sendfile_use_sendfile(self, file, offset=0, count=None):
        #         return super()._sendfile_use_sendfile(file,offset,count)
        #
        # def _sendfile_use_send(self, file, offset=0, count=None):
        #     return super()._sendfile_use_send(file, offset, count)

        # def _check_sendfile_params(self, file, offset, count):
        #     return super()._check_sendfile_params(file, offset, count)
        #
        # def sendfile(self, file, offset=0, count=None):
        #     return super().sendfile(file, offset, count)
        #
        # def _decref_socketios(self):
        #     super()._decref_socketios()
        #
        # def _real_close(self, _ss=_socket.socket):
        #     super()._real_close(_ss)
        #
        # def close(self):
        #     super().close()

        # def detach(self):
        #     super().detach()

        # @property
        # def family(self):
        #     return super().family()
        #
        # @property
        # def type(self):
        #     return super().type

        # if os.name == 'nt':
        #     def get_inheritable(self):
        #         return super().get_inheritable()
        #
        #     def set_inheritable(self, inheritable):
        #         return super().set_inheritable(inheritable)
        # else:
        #     def get_inheritable(self):
        #         return super().get_inheritable()
        #
        #     def set_inheritable(self, inheritable):
        #         return super().set_inheritable(inheritable)


    socket.socket=Guard_socket
    # print("******** Afet import socket")
    import http.client

    def block_network_access(*args, **kwargs):
        raise RuntimeError("Accès réseau interdit : appel bloqué.")

    # urllib3.connection.HTTPConnection
    # requests.adapters.HTTPAdapter.send
    # aiohttp.TCPConnector.connect (si async)
    # ou utilise un proxy (cf plus bas)

    # HTTP client level
    # http.client.HTTPConnection = lambda *args, **kwargs: block_network_access(*args,**kwargs)
    # http.client.HTTPSConnection = lambda *args, **kwargs: block_network_access(*args,**kwargs)

#%% Step 3, use it
from fake_tools import Fake_tools

tools=Fake_tools()
# tools.load_socket()
# tools.load_request()
tools.load_urlopen()
