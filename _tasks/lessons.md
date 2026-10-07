# Lessons

## Sandbox verification

- A test suite must never weaken the sandbox it verifies. `OS_SANDBOX=none` (in a conftest,
  an env file, or a Makefile) disarms the Python guards as well, subprocesses included:
  `py-sandbox=true` then refuses neither `Popen` nor a host outside `net=ALLOW`, while
  `is_in_sandbox()` still answers `True`. Such a suite cannot fail. A provider opt-out in a
  test profile does the same to one layer: `bwrap.share-net=yes` skipped the iptables filter in
  every bwrap test, so a filter that could never load went unnoticed, the Python socket guard
  refusing in its place; the qemu filter was likewise never applied under `python-sb`. Each OS
  layer needs a test with the Python guards off (`py-sandbox=false`), for every provider and
  every launch mode (`python-sb`, daemon).
- Every blocking assertion needs a negative control proving the blocked operation succeeds
  without the sandbox -- and that control must run in its own process. A baseline block leaves
  the `is_in_sandbox()` counter above zero, so an armed block running afterwards in the same
  process short-circuits and silently reproduces the baseline.
- A refusal must be asserted through `sandbox_denials()`, not through an error message.
  Libraries rewrite a blocked connection into wording any outage produces ("All connection
  attempts failed"), so a message assertion passes for the wrong reason.
- A wide `pytest.raises((SandBoxError, NameError, TypeError, AttributeError))` is that same failure in
  another shape. `NameError`, `TypeError` and `AttributeError` prove the payload broke, not that a
  rule refused it, so such a test keeps passing after the barrier it names has been removed. Name
  one exception type, or name a narrow set and assert on what was refused -- a refusal carries the
  target and the rule key for exactly that purpose.
- An escape test whose payload builds a real Popen runs that Popen on the day the guard stops
  holding. Where an escape genuinely succeeds, assert it against a harmless target and say in the
  test name that the configuration reopening it is a configuration error.

## Tests that cannot observe what they call

- A test that calls an API and ignores its return value cannot see that API return the wrong
  thing. `pysandboxes.run()` returned `(result, "_start sandbox in run")` for as long as its
  test called it without asserting the value.
- A profile named in a test but absent from disk puts the run in learning mode, where the
  guards record instead of denying. Such a test is green and verifies nothing.

## Learning mode

- Learning only records what a run actually exercised, and only writes when it observed
  something the profile did not already allow. A run needing nothing new leaves the file
  untouched and prints nothing -- that silence is not a failure.
- Never run learning mode on untrusted code, and inspect any `ALLOW:process-exec` rule a
  learned profile contains before keeping it.
- A framework dependency must never be charged to the user's `python-import` rules. Any
  deferred import pysandboxes makes after `activate_sandboxes()` -- above all on an error path,
  which learning never reaches -- has to go through `preimport_framework_module()`.

## Delegating work in a shared working tree

Uncommitted work is not safe from a subagent. A delegated agent that runs `git stash`,
`git checkout -- <path>`, `git restore`, `git reset`, `git clean` or `git revert` wipes the
whole shared working tree, not just its own sample -- including a human's hand-edited files
and every other agent's work in flight. Recovery is possible but only for tracked files: a
popped stash whose entry is then dropped survives as an unreachable commit
(`git fsck --unreachable`), while untracked files removed by `git clean` are gone for good.

-> Commit before delegating, and forbid every destructive git command in the agent's brief.
An agent that needs to know what a file looked like before reads it with
`git show HEAD:<path>`, which writes nothing. An agent must never `git add` or `git commit`
either: in a shared tree its commit captures everyone else's half-finished work.

-> The index is shared state too, and it may already hold changes that belong to someone else.
`git commit` validates all of it, so staging only the intended paths does not bound what the
commit captures. Commit with an explicit pathspec -- `git commit -- <paths>` -- whenever
`git diff --cached --name-status` lists anything outside the current change, and leave the
foreign entries unstaged rather than restoring them, since restoring guarantees the next
commit swallows them again.

-> A `git stash pop` that conflicts is a signal to read, not to resolve mechanically. Compare
each side against HEAD before choosing: a stale stash can carry back a decision the project
has already reversed, and taking "Stashed changes" reintroduces it silently.

## Classifying runtime values inside a guard

A guard that grades the values an application hands it cannot key that grade on the
identity of objects captured at import time: the other guards replace `builtins` entries
when they arm, so a captured reference stops matching exactly when the sandbox is active.
`__module__` is no better as a qualifier, because it names where a callable was defined
rather than where it is reached -- `open` reports `_io`, `os.listdir` reports `posix`.

-> Match on names or types, resolved at call time. Prefer over-warning to a silent miss:
a value wrongly graded severe is a wording problem, a value missed is a hole. When a set of
module names gates the decision, list the implementation modules beside the facades, and
assert the classification over the whole set rather than a sample -- a six-name sample
passed while the most dangerous entry of the list was misgraded.

-> Run such a classifier's tests with the guards armed. A test suite that arms nothing
exercises the interpreter's own objects, never the patched ones a caller actually sees.

## Typing around ImmutableDict

`ImmutableDict` subclasses `tuple[tuple[K, ...], tuple[V, ...]]`, so mypy resolves an
indexing expression through `tuple.__getitem__` and rejects any attribute access on the
result as `union-attr` -- not `attr-defined`. Every assertion that indexes one and reads a
field off the value needs `# type: ignore[union-attr]`.

-> A `NamedTuple._replace(**mapping)` whose keys reach fields of differing types cannot be
typed either: the key-to-field match is a runtime guarantee of whatever parsed the mapping.
Annotate the unpacking with `# type: ignore[arg-type]` and state that guarantee next to it,
rather than widening the field types to accommodate the checker.

## Asserting that a guard logged a warning

`caplog` formats each record as it captures it, so `record.message` already holds the
interpolated text. Re-applying the arguments (`record.message % record.args`) raises
`TypeError: not all arguments converted during string formatting` and fails a test whose
subject is correct. Assert on `record.getMessage()`, which interpolates on demand and works
whether or not a handler formatted the record.

## A guard that runs after `arm()`

Every guard written so far runs while the sandbox is disarmed, so its own machinery costs
nothing. A guard invoked from user code runs after arming and is charged to the user's
rules: it hands its rewritten AST to the patched `compile`, which refuses it, and starting
its own worker demands `python-api=ALLOW:threads` -- forcing an application to open
threading for all of its code to obtain an eval timeout, a far wider grant than the feature
it pays for.

-> Capture the primitives such a guard needs at import time, before `activate_sandboxes`
installs the patches, and use the captures internally. Capturing the outer callable is not
always enough: `Thread.start` resolves `_start_joinable_thread` as a module global of
`threading`, itself patched, so the captured primitives must be swapped back for the
duration of the call.

-> A guard must consult learning mode before refusing, not after. Learning observes and
never blocks; a refusal on the first call ends the run and leaves nothing to learn from.

## Integration tests for a sandbox layer must prove the layer is on

`os-sandbox=none` leaves the Python layer inactive: no builtin is patched. A suite written
against it passes every "this is refused" assertion by running the payload unguarded, and
reports green while testing nothing.

-> Include one probe asserting a known builtin actually carries its wrapper, so a refusal
that never arrives cannot be confused with a patch that never installed. Use
`os-sandbox=subprocess`, and expose the temporary directory the test writes its script into,
since the confined child cannot otherwise see it.

## An empty parse result means two different things

A guard's `parse_rules` returns the lines it did not claim, and a line no guard claims is
reported as an invalid rule. An empty result therefore reads as "not mine" to the
dispatcher, while the owning guard may have meant "understood, produced nothing". A rule
deliberately reduced to nothing then resurfaces as a syntax error under another message,
and unit tests asserting only the produced rules stay green throughout.

-> A guard returning an empty result for a line it understood must claim that line
explicitly. Assert the unclaimed list is empty, not just that no rule was produced.

## Tolerating a failed resolution must not be symmetric

An `ALLOW` that resolves to nothing grants nothing, so dropping it leaves the default deny
policy in charge. A `DENY` that resolves to nothing is the mirror image: dropping it lifts a
restriction and the connection falls to whatever broader `ALLOW` sits beside it.

-> Before making a rule failure non-fatal, decide per action whether dropping the rule
narrows or widens the profile. Degrade only where the result is a subset of what the author
wrote.

## A denied file read surfaces as a missing module

`guard_files` has no exemption for the interpreter's own library tree; the ambient exemption
named in `guard_eval` covers compile/eval, not file access. An import resolved after the
sandbox arms therefore reads stdlib and site-packages under the profile's `expose-ro=` rules
like any other path. `FileFinder` scans the candidate directory, the guard raises
`RuleFileNotFoundError`, and the import machinery swallows it into a bare `ModuleNotFoundError`
naming neither the path nor the rule -- indistinguishable from a package that was never
installed.

Only lazily-resolved imports reach the disk this late: a PEP 562 `__getattr__` submodule
(`concurrent.futures.thread`, resolved on first attribute access) or a function-local
`import`. A top-level import of the same module resolves before arming and never shows the
problem, so the failure depends on where the import is written rather than on what it names.

-> A profile driving code that imports inside the sandbox must name the interpreter tree
explicitly -- `stdlib` and `purelib` from `sysconfig.get_paths()` -- and never rely on a
project-root rule that happens to cover an in-project venv. That coincidence disappears
wherever the interpreter lives outside the project, as it does in a container.

-> Treat a `ModuleNotFoundError` raised under an armed sandbox as a possible file-rule denial
before trusting it. Confirm the module is genuinely absent by resolving its `__file__` outside
the sandbox; the message alone cannot distinguish the two.

## A static template cannot carry a conditionally valid option

`firejail.template` is concatenated into every firejail command line, so each option it holds
must be valid for every profile. `--x11=none` is not: firejail aborts on it unless the sandbox
owns a network namespace, and the daemon creates one only for profiles declaring `net=` rules.
A profile without them died before reading its configuration -- but only on a host running an
X server, so an environment without one reports the whole provider as healthy.

-> Restrict the static template to options that hold unconditionally. An option whose validity
depends on state computed at launch belongs beside the code establishing that state, where the
two cannot drift apart.

-> Splitting such an option costs whatever guarantee it carried wherever the condition fails.
Emit the strongest form where the condition holds, keep the unconditional part in the template,
and name in both places which guarantee actually survives: a comment asserting a protection the
command line no longer requests is worse than no comment at all.

-> Provider behaviour that varies with the host must be probed on a host that has the feature.
A provider suite green everywhere except one developer's desktop is evidence about the hosts,
not about the provider.

## A sentinel file certifies whatever the recipe failed to check

A recipe that loops over container runtimes and ends with `touch .make-build-image-<variant>`
takes its exit status from that `touch`, not from the builds. `SHELL=/bin/bash` carries no
`-e` and `.SHELLFLAGS` is unset, so a command separated by `;` inside the loop cannot abort it.
A build then fails, make reports success, the sentinel is written, and the variant is never
rebuilt -- the breakage resurfaces later as a container test failing against a stale image.

-> Terminate every build inside such a loop with `|| exit 1`. The sentinel must be unreachable
unless every runtime it claims to cover actually produced an image.

-> Capture both streams when recording a build run: `>log.txt 2>&1`, not `2>&1 >log.txt`.
Docker writes its build progress to stderr, so the reversed form drops exactly the output that
would reveal a failed build, leaving the recipe's silence indistinguishable from success.

## A `ref:` on `actions/checkout` costs the workflow its local run

`act` replaces `actions/checkout` with a bind of the working directory, which is what makes
`make gh-tests` runnable without credentials. It decides by reading the raw `with` map, before
expressions are evaluated, so any `ref:` key disables the substitution -- an expression is a
non-empty string whatever it would evaluate to. The real action then runs, demands a token no
local run holds, and the workflow fails in a way GitHub never reproduces.

-> Pin a branch through a `run:` step guarded by `if: github.event_name == ...`, not through
`ref:`. The step is skipped on the events a local run replays, so `with:` stays free of `ref`.

-> A workflow whose trigger is `schedule:` must pin or assert the branch it tests. GitHub fires the
schedule only from the default branch, and which branch that is lives in a repository
setting, not in the tree: a scheduled job that does not move itself silently follows that
setting wherever it points. Moving the checkout to the branch tip can test a later commit than
the run's `headSha`, so a workflow whose result is reused by commit asserts the branch instead
of re-fetching it.

## A guard wrapper must preserve every documented calling form of the API it patches

Each `@guard_wraps` wrapper replaces a real callable, so an application that reaches the guard
through a valid but less common form breaks before any rule is evaluated -- in learning mode
too, since the failure is at the signature. Two classes recur: narrowing a
`POSITIONAL_OR_KEYWORD` parameter to positional-only (a trailing `/`), which rejects the keyword
form the builtin accepts (`eval`/`exec` with `globals=`/`locals=`, `compile` with `source=`);
and dropping an alternate positional form (`socket.sendto(data, flags, address)` needs a slot
for `flags`, whose address is always the last positional).

-> Wrap with `*args`/`**kwargs` passthrough, or reconstruct the named parameters from them, and
forward exactly what came in. Never re-pass a positional the caller supplied while also
forwarding `**kwargs`, or a keyword call collides ("got multiple values" / "takes at most N").

-> Do not detect this with `inspect.signature(wrapper)`: `guard_wraps` forges `__signature__`
from the original, so introspection reports the API's own shape and hides the mismatch. Read
`wrapper.__code__` / the AST instead, and confirm on the armed path -- an unarmed call short
circuits before the guarded branches run.

## A developer machine hides everything a clean checkout needs

Twelve sample suites passed locally and failed at once in a container, for three reasons that
share one shape: the working machine had been hydrated by hand and never asked again. `uv run
pytest` syncs uv's default group only, so pytest was missing wherever `make init` had not been
run months earlier. Every `.py-sandboxes` exposed the repository as `~/workspace/pysandboxes`,
an absolute path that resolves on exactly one machine. One of them exposed `${TMP}`, a Windows
variable that is unset on a stock Linux shell, leaving an empty rule and a syntax error. None of
this was visible for the lifetime of the workflow, whose tag trigger read the file from a tree
that did not contain it.

-> A target that runs a test suite must also install it. Ordering the install as a separate
recipe line, not a second goal on the same `$(MAKE)`: goals on one command line run concurrently
under `-jN`.

-> A path in a configuration file must be relative to the working directory or carry a default
(`${VAR:-fallback}`). `~` and a bare `${VAR}` encode the author's machine. Learning mode emits
the `~` form because it never walks above PWD, so a regenerated config reintroduces the bug.

-> A sample that spawns a neighbouring sample needs that sample's venv as a declared
prerequisite. Alphabetical order in a list is not a dependency.

## A pickle predicate keyed on the stream's module name is bypassable

`find_class(module, name)` receives two strings the hostile stream chose. A dotted `name` walks
attributes, so an allowed module that imports `os` carries `os.system`, and an allowed class
carries its methods (`Path.unlink`, called by `REDUCE` on an instance the stream builds). A
`from shutil import rmtree` in an allowed module carries `shutil.rmtree` under that module's name.

-> Judge the resolved object, not only the strings: refuse a dotted walk that does not end on a
class, refuse a module object, and check the object's own `__module__` against the denylist too.
A denied module that can parse a nested stream (`pickle`, `marshal`) or build code (`types`)
is a full escape, not a lesser gadget.

-> In unit tests, the autouse guard fixture drops modules from `sys.modules`, so `find_class`
refuses them as "not loaded" before the predicate runs. Put the module back with
`monkeypatch.setitem(sys.modules, ...)` and match the predicate's own refusal message.
