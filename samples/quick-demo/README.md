# Quick demo: learn a policy, then enforce it

A five-minute live demo of pysandboxes, with no framework and no real API key. `app/demo.py` does
three ordinary things: it fetches a URL, reads a directory and reads `DEMO_API_KEY`. The demo starts **without any policy**,
learns one from the script's real behaviour, then runs the same script in another context and shows
what the policy refuses.

Setup, from this directory:

```bash
cd quick-demo
source ./init.sh
```

`init.sh` moves to this directory, removes any previous `.py-sandboxes` and its `.py-sandboxes.old`
backups (the audience must see it being born), exports `DEMO_API_KEY` and an `AWS_SECRET_ACCESS_KEY` the application never needs, and
aliases `python-sb` to this repository's copy until the release `uvx python-sb` needs is published.

## 1. The application, without a sandbox (30 s)

```bash
python app/demo.py --url=https://example.com --dir=data/
```

```
[ OK ]    GET https://example.com: HTTP 200, title=Example Domain
[ OK ]    read data/: hello.txt='Hello from the sandbox demo'
[ OK ]    read $DEMO_API_KEY: sk-...
```

> *Say:* "An ordinary script. Nothing tells us what it is allowed to touch, and nothing stops it if
> someone, or an LLM, makes it do something else."

## 2. Learning mode: the policy writes itself (1 min)

```bash
ls -a                        # no .py-sandboxes
python-sb --learn app/demo.py --url=https://example.com --dir=data/
```

```
[ OK ]    GET https://example.com: HTTP 200, title=Example Domain
[ OK ]    read data/: hello.txt='Hello from the sandbox demo'
[ OK ]    read $DEMO_API_KEY: sk-...

Write all learning rules in '.py-sandboxes'.
Check and update this file to validate the rules.
```

> *Say:* "I changed nothing in the code. I put `python-sb` in front of `python`, and it observed what
> the application really does." Without any policy, `--learn` is even optional: the first run learns.

## 3. Read the policy (1 min)

```bash
grep -E '^(net|expose-ro|expose-rw|python-api|env=DEMO)' .py-sandboxes
```

```
env=DEMO_API_KEY=${DEMO_API_KEY}
expose-ro=./app
expose-ro=./data
net=ALLOW|TCP|example.com|443|OUT
```

- `env=`: the one variable the application reads. The file holds `${DEMO_API_KEY}`, never the key:
  its value is copied from the caller's environment at each start, so the policy can be committed.
  `AWS_SECRET_ACCESS_KEY` is not there, so the application will never see it.
- `net=`: one host, one port, outgoing only.
- `expose-ro=`: read-only access to the application's code and to the one directory it reads,
  not to the rest of the project.
- no `expose-rw=`: the application writes nothing.
- no `python-api=`: it never runs a command, never loads native code.

> *Say:* "This file is the exact inventory of what the application needs. It is readable, it goes
> through code review like the rest of the code, and the OS layer uses the same file. Everything else
> is denied by default."

## 4. Replay in the learned context (20 s)

```bash
python-sb app/demo.py --url=https://example.com --dir=data/
```

Same three `[ OK ]`: the policy is enforced, and the legitimate use still works.

To show how a value is given, edit the `env=` line and replay:

- `env=DEMO_API_KEY=sk-fake-for-tests`: a fixed value, whatever the caller has;
- `env=*_API_KEY=${*_API_KEY}`: every `*_API_KEY` of the caller, forwarded;
- delete the line: `read $DEMO_API_KEY` is refused with `KeyError`, even though the variable is set.

## 5. The same script, in another context (1 min 30)

```bash
python-sb app/demo.py --url https://www.wikipedia.org --dir ~
```

```
Connection to '[185.15.58.224]:443' DENIED by implicit default policy.
[REFUSED] GET https://www.wikipedia.org: URLError: <urlopen error Guard network connection to '[185.15.58.224]:443' DENIED by implicit default policy.>
[REFUSED] read /home/<user>/: RuleFileNotFoundError: Access to '/home/<user>' must be accepted by a rule.
```

> *Say:* "Same code, other arguments. The policy does not care why the script wants to go elsewhere:
> it was not learned, so it is refused."

Now the case that matters for AI-generated code: `--evil` simulates what a prompt injection could slip
into the same application.

```bash
python-sb app/demo.py --evil
```

```
[ OK ]    GET https://example.com: HTTP 200, title=Example Domain
[ OK ]    read data/: hello.txt='Hello from the sandbox demo'
[ OK ]    read $DEMO_API_KEY: sk-...
[REFUSED] read an SSH key: RuleFileNotFoundError: Access to '/home/<user>/.ssh/id_rsa' must be accepted by a rule.
[REFUSED] read /etc/passwd: RuleFileNotFoundError: Access to '/etc/passwd' must be accepted by a rule.
[REFUSED] run a shell command: RuleApiPermissionError: os.system() is denied by the API guard (category: process-exec).
Add `python-api=ALLOW:os.system` for this function only, or `python-api=ALLOW:process-exec` for the whole category.
[ OK ]    list secrets in the environment: DEMO_API_KEY
[REFUSED] read $AWS_SECRET_ACCESS_KEY: KeyError: 'AWS_SECRET_ACCESS_KEY'
[REFUSED] exfiltrate: URLError: <urlopen error Guard network connection to '[162.159.142.41]:443' DENIED by implicit default policy.>
```

> *Say:* "Reading a key, running a shell, sending data out: none of it was learned, none of it
> passes. Looking for secrets finds only the one key the application was given: the AWS secret set in
> my shell never reached it. And the application keeps working for what it was built to do."

## 6. Widen the policy on purpose (1 min)

The new context is legitimate after all: learn it, on top of the current policy.

```bash
python-sb --learn app/demo.py --url https://www.wikipedia.org --dir ~
```

```
[ OK ]    GET https://www.wikipedia.org: HTTP 200, title=Wikipedia
[ OK ]    read /home/<user>/: .bash_history='...', .bashrc='# ~/.bashrc: executed by bash(1', ...
[ OK ]    read $DEMO_API_KEY: sk-...

Write all learning rules in '.py-sandboxes'.
The old version is here '.py-sandboxes.old'.
Check and update this file to validate the rules.
```

Learning only adds rules; the new rights are the difference between the two files:

```bash
diff .py-sandboxes.old .py-sandboxes
```

```
98a99,101
> # Add rules (<date>)
> expose-ro=~
>
142a146,148
>
> # Add rules (<date>)
> net=ALLOW|TCP|www.wikipedia.org|443|OUT
```

Replay without `--learn`, with the new rights:

```bash
python-sb app/demo.py --url https://www.wikipedia.org --dir ~
```

```
[ OK ]    GET https://www.wikipedia.org: HTTP 200, title=Wikipedia
[ OK ]    read /home/<user>/: .bash_history='...', .bashrc='# ~/.bashrc: executed by bash(1', ...
[ OK ]    read $DEMO_API_KEY: sk-...
```

> *Say:* "Two lines, one per new need, and the new context works. But `expose-ro=~` also covers
> `~/.ssh`: with this policy, `--evil` reads the SSH key. A diff is where a too-broad right is caught."

Put the reviewed policy back before going on:

```bash
mv .py-sandboxes.old .py-sandboxes
```

## 7. Bonus: the kernel boundary (30 s)

The refusals above come from the Python layer, which a determined attacker can bypass with compiled
code. The OS layer applies the same policy through the kernel:

```bash
OS_SANDBOX=landlock python-sb app/demo.py --evil
```

> *Say:* "Same file, now enforced by the Linux kernel. This one also holds against `ctypes` or a
> native extension."

## 8. Learning trusts what it sees (1 min)

Learn again, but this time with the injected behaviour:

```bash
python-sb --learn app/demo.py --evil
```

```
[ OK ]    GET https://example.com: HTTP 200, title=Example Domain
[ OK ]    read data/: hello.txt='Hello from the sandbox demo'
[ OK ]    read $DEMO_API_KEY: sk-...
[ OK ]    read an SSH key: -----BEGIN RSA PRIVATE KEY----
[ OK ]    read /etc/passwd: root:x:0:0:root:/root:/bin/bash
[ OK ]    run a shell command: exit code 0
[ OK ]    list secrets in the environment: AWS_SECRET_ACCESS_KEY, DEMO_API_KEY
[ OK ]    read $AWS_SECRET_ACCESS_KEY: do-...
[ OK ]    exfiltrate: HTTP 200, title=?

Write all learning rules in '.py-sandboxes'.
The old version is here '.py-sandboxes.old'.
Check and update this file to validate the rules.
```

Everything passes: in learning mode the application sees the whole environment, and reads the value of
`AWS_SECRET_ACCESS_KEY`. The previous policy is kept aside, and the impact of this run is the difference
between the two files:

```bash
diff .py-sandboxes.old .py-sandboxes
```

```
62a63,65
> # Add rules (<date>)
> env=AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
>
98a102,105
> # Add rules (<date>)
> expose-ro=/etc
> expose-ro=~/.ssh
>
143a151,153
> # Add rules (<date>)
> net=ALLOW|TCP|postman-echo.com|443|OUT
>
207a218,221
>
> # Add rules (<date>)
> # ⚠ process-exec: runs code outside the patched interpreter
> python-api=ALLOW:os.system
```

> *Say:* "Learning records what the code does, including what it should not do. Learn from a trusted
> run, and review this diff like any other code change: here, five lines give away the attack, and
> the first one would hand the AWS secret to every future run."

Put the reviewed policy back before replaying:

```bash
mv .py-sandboxes.old .py-sandboxes
```

## Recording the demo

`demo.sh` plays steps 1 to 5 unattended, up to the first `--evil`, with a comment before each command,
for [asciinema](https://asciinema.org) and its GIF converter [agg](https://github.com/asciinema/agg).
It runs under `bwrap`, with `HOME=/home/pysandboxes` on a tmpfs that exists only for the demo, so the
refused `--dir ~` shows no real user name.

```bash
asciinema rec --overwrite --cols 110 --rows 12 -c ./demo.sh ../quick-demo.cast
agg ../quick-demo.cast quick-demo.gif
```

`TYPE_DELAY` (seconds per character) and `PAUSE` (seconds after each command) set the pace.
