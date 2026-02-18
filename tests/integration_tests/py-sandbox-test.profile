env=HOME=${HOME}
env=USER=${USER}
env=VIRTUAL_ENV*=${VIRTUAL_ENV*}
env=LC_*=${LC_*}
env=LD_LIBRARY_PATH=${LD_LIBRARY_PATH}
env=LANG=${LANG}
env=TMP=/tmp
env=TEMP=/tmp


# Ignores all hidden files and .log files
ignore=.*
ignore=*.log
ro-bind=${PWD},${PWD}
ro-bind=${PYENV_ROOT},${PYENV_ROOT}
ro-bind=${VIRTUAL_ENV},${VIRTUAL_ENV}

python-import=os
python-import=socket
python-import=io
python-import=tempfile,shutil


