set-env=HOME=${HOME}
set-env=USER=${USER}
set-env=VIRTUAL_ENV*=${VIRTUAL_ENV*}
set-env=LC_*=${LC_*}
set-env=LD_LIBRARY_PATH=${LD_LIBRARY_PATH}
set-env=LANG=${LANG}
set-env=TMP=/tmp
set-env=TEMP=/tmp


# Ignores all hidden files and .log files
ignore=.*
ignore=*.log
ro-bind=${PWD},${PWD}
ro-bind=${PYENV_ROOT},${PYENV_ROOT}
ro-bind=${VIRTUAL_ENV},${VIRTUAL_ENV}

python-import=os
python-import=socket
python-import=io

