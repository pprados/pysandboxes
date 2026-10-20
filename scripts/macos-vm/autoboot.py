# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Pick "Macintosh HD" in the OpenCore picker, whose default entry is "EFI".

Started by boot-ssh.sh. It reads the screen through QMP, so the picker coordinates assume the 1920x1080 firmware
variables that OSX-KVM boots with."""

import json
import os
import socket
import sys
import tempfile
import time

QMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qmp.sock")


def qmp(cmd):
    s = socket.socket(socket.AF_UNIX)
    s.connect(QMP)
    f = s.makefile("rw")
    f.readline()
    for c in ({"execute": "qmp_capabilities"}, cmd):
        f.write(json.dumps(c) + "\n")
        f.flush()
        while not {"return", "error"} & json.loads(f.readline()).keys():
            pass
    s.close()


def pixel(ppm, x, y):
    with open(ppm, "rb") as f:
        parts = f.read(64).split(maxsplit=4)
        w = int(parts[1])
        f.seek(len(b" ".join(parts[:4])) + 1 + 3 * (y * w + x))
        return f.read(3)


def picker_shown(ppm):
    # Highlighted "EFI" tile is grey on a black screen.
    return min(pixel(ppm, 497, 322)) > 0x60 and max(pixel(ppm, 100, 100)) < 0x10


def main():
    ppm = os.path.join(tempfile.gettempdir(), f"osx-kvm-{os.getpid()}.ppm")
    # Watch for the whole VM life: every guest reboot goes through the picker again.
    connected = False
    start = time.time()
    while True:
        time.sleep(2)
        try:
            qmp({"execute": "screendump", "arguments": {"filename": ppm}})
            connected = True
            if picker_shown(ppm):
                for k in ("right", "ctrl-ret"):
                    keys = [{"type": "qcode", "data": c} for c in k.split("-")]
                    qmp({"execute": "send-key", "arguments": {"keys": keys}})
                    time.sleep(0.3)
                print("autoboot: Macintosh HD selected", flush=True)
                time.sleep(20)
        except OSError:
            if connected or time.time() - start > 60:
                return 0
        finally:
            if os.path.exists(ppm):
                os.remove(ppm)


if __name__ == "__main__":
    sys.exit(main())
