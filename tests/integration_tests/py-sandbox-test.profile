#learn=tests/integration_tests/py-sandbox-test.profile
py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
include "pycharm.profile"

env=HOME=${HOME}
env=LANGUAGE=${LANGUAGE}
env=My_ENV=${My_ENV}
env=PYDANTIC_DISABLE_PLUGINS=${PYDANTIC_DISABLE_PLUGINS}
env=PYDANTIC_VALIDATE_CORE_SCHEMAS=${PYDANTIC_VALIDATE_CORE_SCHEMAS}
env=PYTHONUSERBASE=${PYTHONUSERBASE}

# ⚠ Dangerous!
python-import=atexit, importlib, inspect, subprocess

# Standard Python
python-import=__future__, _hashlib, _io, _multibytecodec, _socket
python-import=_sysconfigdata__linux_x86_64-linux-gnu, _zoneinfo, abc, array, ast
python-import=asyncio, base64, binascii, calendar, codecs, collections, colorsys
python-import=concurrent, contextlib, contextvars, copy, copyreg, dataclasses
python-import=datetime, decimal, email, encodings, enum, errno, fractions, functools
python-import=hashlib, hmac, html, http, io, ipaddress, itertools, json, keyword
python-import=logging, math, mimetypes, netrc, operator, os, pathlib, pickle, queue
python-import=random, re, secrets, select, shlex, signal, socket, ssl, stat
python-import=stringprep, struct, sysconfig, tempfile, textwrap, threading, time
python-import=traceback, types, typing, unicodedata, urllib, uuid, weakref, zipfile
python-import=zlib, zoneinfo

# External modules (Are you sure about the origin?)
python-import=annotated_types
python-import=anyio
python-import=certifi
python-import=charset_normalizer
python-import=email_validator
python-import=fastapi
python-import=h11
python-import=idna
python-import=pydantic
python-import=pydantic_core
python-import=requests
python-import=rich
python-import=sniffio
python-import=starlette
python-import=tests
python-import=typing_extensions
python-import=typing_inspection
python-import=urllib3
python-import=uvicorn

bind=./tmp,./tmp
ro-bind=.,.

net=ALLOW|TCP|0.0.0.0/32|59115|IN
net=ALLOW|TCP|ip6-localhost|9999,0|IN
net=ALLOW|TCP|localhost|9999|IN
net=ALLOW|TCP|www.google.com|80|OUT
net=ALLOW|UDP|ip6-localhost|12345|OUT
net=ALLOW|UDP|localhost|12345|IN
net=ALLOW|UDP|localhost|12346,12345|OUT

# Add rules (2025/10/30 at 12:42)
net=ALLOW|TCP|0.0.0.0/32|34769|IN
net=ALLOW|TCP|ip6-localhost|0,9999|IN
net=ALLOW|UDP|localhost|12345,12346|OUT
