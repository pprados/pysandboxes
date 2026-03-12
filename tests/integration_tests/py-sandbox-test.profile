include "./.local.py-sandboxes"  # May be add to .gitignore
include "~/.config/py-sandboxes/user-py-sandboxes.profile"  # For all project for user
include "/etc/py-sandboxes/global-py-sandboxes.profile"  # For all the node
py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
env=HOME=${HOME}
env=LANGUAGE=${LANGUAGE}
env=My_ENV=${My_ENV}
env=PYDANTIC_DISABLE_PLUGINS=${PYDANTIC_DISABLE_PLUGINS}
env=PYDANTIC_VALIDATE_CORE_SCHEMAS=${PYDANTIC_VALIDATE_CORE_SCHEMAS}
env=PYTHONUSERBASE=${PYTHONUSERBASE}

python-import=*

bind=./tmp,./tmp
ro-bind=.,.
ro-bind=~/.cache/JetBrains/,~/.cache/JetBrains/
ro-bind=~/.local/share/JetBrains/,~/.local/share/JetBrains/
ro-bind=~/.local/share/uv/,~/.local/share/uv/

net=ALLOW|TCP|0.0.0.0/32|50983|IN
net=ALLOW|TCP|ip6-localhost|9999,0|IN
net=ALLOW|TCP|localhost|9999|IN
net=ALLOW|TCP|www.google.com|80|OUT
net=ALLOW|UDP|ip6-localhost|12345|OUT
net=ALLOW|UDP|localhost|12345|IN
net=ALLOW|UDP|localhost|12346,12345|OUT

# Add rules (2025/11/12 at 14:13)
net=ALLOW|TCP|0.0.0.0/32|53373|IN
net=ALLOW|UDP|localhost|12345,12346|OUT

# Add rules (2025/11/12 at 14:13)
net=ALLOW|TCP|0.0.0.0/32|41131|IN

# Add rules (2025/11/12 at 14:13)
net=ALLOW|TCP|0.0.0.0/32|41177|IN
net=ALLOW|TCP|ip6-localhost|0,9999|IN
