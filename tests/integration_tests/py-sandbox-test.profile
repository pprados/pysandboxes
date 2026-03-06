env=LANGUAGE=${LANGUAGE}
env=PYTHONUSERBASE=${PYTHONUSERBASE}

# ⚠ Dangerous!
python-import=subprocess

# Standard Python
python-import=_decimal, _pytest, _sysconfigdata__linux_x86_64-linux-gnu, _zoneinfo
python-import=_io, __future__, sys, abc, builtins, _socket, itertools, math, errno, concurrent, binascii, _operator, time, array, codecs
python-import=atexit,unicodedata,marshal,gc
python-import=argparse, ast, asyncio, base64, bdb, bisect, bz2, collections
python-import=colorsys, configparser, contextlib, contextvars, copy, copyreg
python-import=dataclasses, datetime, decimal, difflib, dis, email, encodings, enum
python-import=fnmatch, fractions, functools, genericpath, gettext, glob, hashlib
python-import=heapq, hmac, html, http, importlib, inspect, io, ipaddress, json
python-import=keyword, linecache, locale, logging, lzma, mimetypes, multiprocessing
python-import=ntpath, numbers, operator, os, pathlib, pickle, platform, posixpath
python-import=pprint, queue, quopri, random, re, reprlib, secrets, selectors, shlex
python-import=shutil, signal, socket, socketserver, ssl, stat, string, struct
python-import=sysconfig, tempfile, textwrap, threading, token, tokenize, traceback
python-import=types, typing, unittest, urllib, uuid, warnings, weakref, zipfile
python-import=zoneinfo


# External modules (Are you sure about the origin?)
python-import=annotated_types
python-import=anyio
python-import=click
python-import=email_validator
python-import=fastapi
python-import=h11
python-import=idna
python-import=iniconfig
python-import=opcode
python-import=pluggy
python-import=py
python-import=pydantic
python-import=pydantic_core
python-import=pytest
python-import=python_multipart
python-import=sniffio
python-import=starlette
python-import=tblib
python-import=tests
python-import=typing_extensions
python-import=typing_inspection
python-import=uvicorn
python-import=pygments
python-import=rich

ro-bind=.,.

net=ALLOW|TCP|*|55109|IN

include "pycharm.profile"