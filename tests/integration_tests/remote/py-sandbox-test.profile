include "./.local.py-sandboxes"  # May be add to .gitignore
py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
env=PYTHONUSERBASE=${PYTHONUSERBASE}
ro-bind=.,.
net=ALLOW|TCP|0.0.0.0/32|*|IN
python-import=*
