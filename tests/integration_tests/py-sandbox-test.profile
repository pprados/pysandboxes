#--os-sandbox=task
--os-sandbox=subprocess
# --os-sandbox=firejail
# TODO --no-py-sandbox
# TODO: --no-dotenv
# TODO: --firejail=file.template

--set-env=HOME=${HOME}
--set-env=USER=${USER}
--set-env=PATH=${PATH}  # FIXME je ne pense pas cela nécessaire
--set-env=VIRTUAL_ENV*=${VIRTUAL_ENV_*}
--set-env=LC_*=${LC_*}
--set-env=LD_LIBRARY_PATH=${LD_LIBRARY_PATH}
--set-env=LANG=${LANG}
--set-env=TMP=/tmp
--set-env=TEMP=/tmp


# Ignores all hidden files and .log files
--ignore=.*
--ignore=*.log
--ro-bind=${PWD},${PWD}
--ro-bind=${PYENV_ROOT},${PYENV_ROOT}
--ro-bind=${VIRTUAL_ENV},${VIRTUAL_ENV}
