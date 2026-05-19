os-sandbox=toto
os-sandbox=subprocess
os-sandbox=firejail
set-env=ERROR
expose-ro=${PWD},not_exist
expose-rw=not_exist,${PWD}
expose-ro=abc
ignore-parameter
port=abc

net=ERROR
net=ERROR|tcp|127.0.0.1/32|8000|IN
net=ALLOW||127.0.0.1/32|8000|IN
net=ALLOW|any,tcp,udp|127.0.0.1/32|8000|IN
net=ALLOW|*,tcp,udp|127.0.0.1/32|8000|IN
net=ALLOW|toto|127.0.0.1/32/32|8000|IN
net=ALLOW|tcp||8000|IN
net=ALLOW|tcp|*|8000|IN
net=ALLOW|tcp|acme.acme|*|IN
net=ALLOW|tcp|0.0.0.0/0|a,b|IN
net=ALLOW|tcp|0.0.0.0/0|*|

expose-rw=${PWD},${PWD}/tests
expose-rw=${PWD},${PWD}/tests/unit_tests
expose-ro=${PWD},${PWD}/tests
py-sandbox=abc
learn=True
invalide-rule
