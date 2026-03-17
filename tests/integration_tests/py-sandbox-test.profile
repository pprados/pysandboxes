include "./.local.py-sandboxes"  # May be add to .gitignore

py-sandbox=true
os-sandbox=${OS_SANDBOX:-subprocess}
env=LANGUAGE=${LANGUAGE}
env=My_ENV=${My_ENV}

python-import=*

bind=./tmp,./tmp
ro-bind=.,.

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
