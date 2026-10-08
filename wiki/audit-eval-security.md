# Security assessment of the `eval-*` guard — attacks and what stops them

This page is a red-team report on the dynamic-code guard (`eval()`, `exec()`,
`compile()` and the `guarded_eval()` wrapper). It documents, attack by attack,
what a hostile string can and cannot do once a profile is declared, which
layer stops each attempt, and the residual limits the guard does **not**
claim to cover.

It is a companion to [the `eval-*` rules](eval.md), which describes the
configuration keys, and to [weaknesses](weaknesses.md), which lists the limits
of the package as a whole. Read this one when you need to reason about *what an
attacker can reach*, not about *how to write a rule*.

**Verification date: 2026-10-06.** On Python 3.13.5, the focused eval-rule,
transform, runtime, hardening and attack-matrix suites reported 197 passed and
2 skipped. The skips cover template strings, a Python 3.14 syntax feature; they
do not skip the guard's general eval tests.

Every attack below is pinned as an executable test in
[`test_eval_attack_matrix.py`](../tests/unit_tests/guard/test_eval_attack_matrix.py)
(blocked attacks and allowed payloads) or
[`test_eval_hardening.py`](../tests/unit_tests/guard/test_eval_hardening.py)
(per-rule regression). A tested result applies to its payload and configuration;
it does not establish that every equivalent attack is blocked.

## Summary

The `eval-*` layer is designed for a source string evaluated in a bounded
namespace. Static validation is a usability check; the namespace and runtime
helpers enforce the declared capabilities. The assessment demonstrates blocked
escape attempts, allowed payloads, and residual denial-of-service risks. It is
not an OS security boundary and does not assess arbitrary bytecode running in
the host interpreter; see the [Python-layer assessment](audit-python-security.md)
for that distinct threat model.

---

## Table of contents

- [The threat model in one paragraph](#the-threat-model-in-one-paragraph)
- [Three layers, two of which enforce](#three-layers-two-of-which-enforce)
- [The master lever: capability builtins](#the-master-lever-capability-builtins)
- [Attack matrix — escapes that are blocked](#attack-matrix--escapes-that-are-blocked)
- [Attack matrix — payloads that still run](#attack-matrix--payloads-that-still-run)
- [The `str.format` blind spot](#the-strformat-blind-spot)
- [Lambdas and the call-depth budget](#lambdas-and-the-call-depth-budget)
- [Residual limits — denial of service](#residual-limits--denial-of-service)
- [Things that look like holes but are not](#things-that-look-like-holes-but-are-not)
- [Reproducing the assessment](#reproducing-the-assessment)

---

## The threat model in one paragraph

The attacker controls the **source string** handed to `eval`/`exec`/`compile`
or to `guarded_eval()` — this is exactly the shape of an LLM's answer. The
attacker does **not** control the profile: the `.py-sandboxes` rules are
written by the application author. The goal of an escape is to reach something
the profile did not grant — a module (`os`), the host process frames, an
arbitrary class hierarchy, or code execution (`Popen`). Everything else
(exhausting CPU or memory) is denial of service, treated separately at the end.

The empty-`__builtins__` trick that many tools rely on is **not** a defence:

```python
result = eval(expression, {"__builtins__": {}}, {})
# defeated by:
"[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/sh'])"
```

The `eval-*` guard exists precisely because that pattern fails.

---

## Three layers, two of which enforce

| Layer | Where | Role | Bypassable alone? |
|---|---|---|---|
| **Static validation** | `eval_transform._Validator` | *fail-fast* — rejects a source that names a refused node, dunder, call or import | **Yes**, trivially: a dynamically built name is never seen. It is a courtesy to the rule author, not a barrier. |
| **Bounded namespace** | `guard_eval.build_namespace` | the evaluated code sees only `__builtins__` built from `eval-call`, the injected helpers, and wrapper `names` | **No** — an ungranted name simply does not exist |
| **Runtime helpers** | `eval_runtime` | `__sb_getattr__`, `__sb_binop__`, tick/enter budgets, the frame-capture DENY | **No** — every attribute read, whatever its syntax, passes through `_check_attr` |

The design principle: **static validation catches nothing an attacker cannot
route around. The namespace and the runtime helpers are the real barriers.**
No known way reaches an attribute *without* going through `_check_attr`,
`string.Formatter` included (see [the `str.format` section](#the-strformat-blind-spot)).

---

## The master lever: capability builtins

A handful of builtins hand back, *by their own name*, a door the bounded
namespace had shut. The sharpest is `getattr`: the raw builtin reads any
attribute in C, so binding it unguarded would reopen `eval-magic`, `eval-attribute`
**and** the frame-capture DENY at once.

```python
# with eval-call=getattr and nothing else, the raw builtin would be a full escape:
getattr((), '__class__')                       # -> <class 'tuple'>   (eval-magic bypassed)
getattr(getattr(gen, 'gi_frame'), 'f_globals') # -> real globals      (FRAME_CAPTURE bypassed)
```

These builtins are **bound under their own name to a guarded shim**, so
`eval-call=getattr` grants the *name* but not the bypass. The shims live in
`eval_runtime.GUARDED_BUILTINS`:

| Builtin | Guarded behaviour |
|---|---|
| `getattr(obj, name[, default])` | routed through `__sb_getattr__` — the name is checked (`eval-magic` / `eval-attribute` / frame-capture) before the read; the 3-argument default applies only after the name is allowed |
| `hasattr(obj, name)` | same check; a refused name raises, it does not silently return `False` |
| `vars(obj)` | routed to `__sb_getattr__(obj, "__dict__")`, so it is gated by `eval-magic=__dict__`; `vars()` with no argument is refused (it exposes the evaluation frame) |
| `setattr` / `delattr` | refused outright — attribute store and delete are not part of the sub-language |
| `type(x)` | allowed (the returned class stays gated on every attribute); `type(name, bases, dict)` — the class factory — is refused |
| `dir()` | no-argument form refused; `dir(obj)` filtered to the names the rules would allow |
| `globals()` | refused — the evaluation namespace is never handed back |
| `breakpoint()` | refused — the debugger reaches the host |

`open`, `eval`, `exec`, `compile` and `__import__` are **deliberately absent**
from that table: each already reaches its own guard (the file rules, this guard
re-entered, the import rules). Granting any sensitive builtin via `eval-call`
logs a warning at configuration-parse time.

---

## Attack matrix — escapes that are blocked

Every row is refused. "Layer" names what actually stops it. All are pinned in
`test_eval_attack_matrix.py::test_attack_is_blocked`.

| Attack | Payload | Minimal config | Stopped by |
|---|---|---|---|
| dunder by dot | `().__class__` | *(defaults)* | static (`eval-magic`) |
| f-string attribute | `f'{ ().__class__ }'` | `eval-syntax=fstring` | static (`eval-magic`) |
| t-string attribute (3.14) | `t'{ ().__class__ }'` | `eval-syntax=tstring` | static (`eval-magic`) |
| `import` statement | `import os` | `eval-syntax=import` | static (`eval-import`) |
| frame by dot | `(i for i in ()).gi_frame` | `eval-syntax=comprehension` | runtime — frame-capture DENY |
| getattr → dunder | `getattr((), '__class__')` | `eval-call=getattr` | runtime — `__sb_getattr__` |
| getattr → frame | `getattr(getattr((i for i in [1]),'gi_frame'),'f_globals')` | `eval-call=getattr` | runtime — frame-capture DENY |
| getattr → subclasses → Popen | `[c for c in getattr(getattr(getattr((),'__class__'),'__base__'),'__subclasses__')() if getattr(c,'__name__')=='Popen']` | `eval-call=getattr,list` | runtime — dies on `__class__` |
| getattr default on refused name | `getattr((), '__class__', 'x')` | `eval-call=getattr` | runtime — default does **not** swallow the refusal |
| `setattr` | `setattr(o, 'x', 7)` | `eval-call=setattr` | runtime — store refused |
| `delattr` | `delattr(o, 'x')` | `eval-call=delattr` | runtime — delete refused |
| `vars(obj)` | `vars(o)` | `eval-call=vars` | runtime — gated by `eval-magic=__dict__` |
| `vars()` | `vars()` | `eval-call=vars` | runtime — frame exposure refused |
| class factory | `type('X', (), {})` | `eval-call=type` | runtime — 3-arg `type` refused |
| `globals()` | `globals()` | `eval-call=globals` | runtime — refused |
| `breakpoint()` | `breakpoint()` | `eval-call=breakpoint` | runtime — refused |
| `dir()` | `dir()` | `eval-call=dir` | runtime — frame exposure refused |
| `str.format` → dunder | `'{0.__class__}'.format(())` | `eval-attribute=format` | runtime — template validated |
| `str.format` on the class | `str.format('{0.__class__}', ())` | `eval-call=str`, `eval-attribute=format` | runtime — unbound template validated |
| `str.format` via `type('')` | `type('').format('{0.__class__}', ())` | `eval-call=type`, `eval-attribute=format` | runtime — unbound template validated |
| `format_map` → dunder | `'{0.__class__}'.format_map([()])` | `eval-attribute=format_map` | runtime — template validated |
| nested format spec | `'{0:{1.__class__}}'.format(3, 4)` | `eval-attribute=format` | runtime — spec field validated |
| lambda recursion | `(lambda g: g(g))(lambda f: f(f))` | `eval-syntax=func`, `eval-call=f,g` | runtime — `eval-max-call-depth` |
| def recursion | `def f(n): return f(n+1)` … | `eval-syntax=func,arith`, `eval-call=f` | runtime — `eval-max-call-depth` |
| generator recursion | `def g(n): yield from g(n+1)` … | `eval-syntax=func,yield,…` | runtime — `eval-max-call-depth` |
| comprehension flood | `[0 for _ in range(10**9)]` | `eval-syntax=comprehension,arith`, `eval-call=range` | runtime — `eval-max-iterations` tick |
| pow allocation | `2 ** 80000` | `eval-syntax=arith` | runtime — `eval-max-alloc` on `**` |
| mro hop to subclasses | `getattr(type(()).mro()[1], '__subclasses__')` | `eval-call=type,getattr`, `eval-attribute=mro` | runtime — `__subclasses__` is magic-gated |
| helper name reference | `__sb_getattr__((), 'x')` | any | static — reserved `__sb_` prefix |
| lambda closure walk | `(lambda f: f.__closure__)(lambda: 0)` | `eval-syntax=func`, `eval-call=f` | static — `__closure__` is a dunder |

---

## Attack matrix — payloads that still run

Two families run to completion on purpose: the calculator's legitimate work,
and the denial-of-service payloads the guard documents as out of reach of an
AST-level check. Pinned in `test_eval_attack_matrix.py::test_payload_runs`.

| Payload | Config | Why it runs |
|---|---|---|
| `2 + 3 * 4` | `eval-syntax=arith` | legitimate arithmetic |
| `[x*2 for x in range(3)]` | `eval-syntax=comprehension,arith`, `eval-call=range` | legitimate comprehension |
| `type(())` | `eval-call=type` | 1-argument `type` is a safe query |
| `'{0}-{1[0]}'.format(5, (7,))` | `eval-attribute=format` | data-only format, no attribute access |
| `'ab'.upper()` | `eval-attribute=upper` | granted string method |
| `sum(range(2000))` | `eval-call=sum,range` | **DoS**: a C loop charges no tick; see below |
| `bytes(5000)` (budget 100) | `eval-call=bytes` | **DoS**: allocation outside `+`/`*`/`**` |
| `'%0500d' % 1` (budget 100) | *(arith)* | **DoS**: `%` is not a rewritten operator |

---

## The `str.format` blind spot

`str.format` resolves `{0.__class__}` **in C**, from the contents of the
string. No `Attribute` node exists for static validation or for
`__sb_getattr__` to see — so `format` is a structural blind spot, curated out
of `str-methods` by default and only grantable with a warning.

The guard **validates the template at runtime**. When `eval-attribute`
grants `format`, `__sb_getattr__` does not return the raw bound method: it
returns a wrapper. That wrapper walks every field of the template with
`_string.formatter_field_name_split` and runs each attribute access through
`_check_attr`. Only then does it delegate to the real method. Index access
(`{0[0]}`) is data and left alone; nested spec fields (`{0:{1.__class__}}`) are
walked in turn.

A second door, reaching the method through the **class** rather than an
instance, is closed as well:

```python
str.format('{0.__class__}', ())        # unbound: template is the first argument
type('').format('{0.__class__}', ())   # same, reached through type()
```

The instance wrapper does not cover these, because the object to the left of the
dot is the `str` *class*, not a string. Both are validated by an unbound
wrapper (`_guarded_format_unbound`), which also covers `str` subclasses.

A third door is `string.Formatter`. Its
`format`, `vformat` and `get_field` resolve the same fields in Python, and
`__sb_getattr__` wraps `format` only when the object is a `str`:

```python
F.format('{0.__class__.__base__}', ())   # names={"F": string.Formatter()}, eval-attribute=format
# refused
```

The same holds with `eval-import=string`, `eval-call=Formatter,__import__` and
`eval-attribute=Formatter,format`. Validating the template before the call
would not be enough: a subclass can override `parse` and hand `get_field` a
field the template never showed. So the guard patches the one place the
attribute is read, `string.Formatter.get_field`: during a guarded evaluation,
every field it receives goes through `_check_attr`; outside one, the method is
untouched. Pinned in `test_eval_hardening.py` and, for the patch installed at
startup, in `tests/integration_tests/test_eval_integration.py`.

That check reads the evaluation state of the *current* thread, which leaves a
fourth door: a `Formatter` method handed to an executor the application
supplied runs on a thread with no state.

```python
X.submit(F.format, '{0.__class__.__base__}', ()).result()   # names={"F": ..., "X": ThreadPoolExecutor()}
# refused
```

A method fetched from a `Formatter` (instance or class) by the evaluated code
carries the fetching evaluation's state, and pushes it on whatever thread
calls it. Threads of the application that use a `Formatter` on their own stay
untouched.

Two configuration rules keep the method out of reach in the first place:

- **Only the exact name grants `format` or `format_map`.** `eval-attribute=*`
  or `f*` leave both refused; a wide grant never opens them by accident.
- **The refusal points to the f-string**, whose attribute accesses are checked
  like any dotted read, rather than telling the reader to grant `format`.

**Recommendation: write an f-string, not `str.format()`.** `f"{x.name}"`
compiles to `JoinedStr` and `FormattedValue` nodes, so each attribute it reads
is an ordinary `Attribute` node, checked statically and by `__sb_getattr__`. It
needs `eval-syntax=fstring`, and no `format` grant. `str.format` leaves the
fields to the runtime template walk described above, and every door closed in
this section was a way around that walk. Keep `eval-attribute=format` for code
that cannot be changed. When learning mode observes `format` or `format_map`, it
writes this advice as a comment above the generated `eval-attribute` line.

---

## Lambdas and the call-depth budget

A `FunctionDef` body is rewritten with an inline `__sb_enter__()` /
`try … finally __sb_leave__()` bracket, so recursion charges a call frame and
is bounded by `eval-max-call-depth`. A **lambda** body is a single expression
that admits no statement, so it cannot carry that bracket itself:

```python
(lambda g: g(g))(lambda f: f(f))   # EvalInterrupted(eval-max-call-depth)
```

Lambdas are wrapped at definition — `_Injector.visit_Lambda` rewrites
`lambda … : body` into `__sb_func__(lambda … : body)`, and `__sb_func__`
brackets every call with enter/leave. Lambda recursion is bounded exactly
like a function, raising `EvalInterrupted(eval-max-call-depth)` rather than a
catchable `RecursionError`. Generator recursion (`yield from`) is
bounded too, because the inline bracket's `__sb_enter__` runs on each
`next()` as the delegation chain deepens.

---

## Residual limits — denial of service

These are **documented limits**, not oversights. They are out of reach of an
AST-level guard and are guaranteed only by the OS layer, where a timeout is a
process kill.

| Limit | Example | Why the Python layer cannot stop it |
|---|---|---|
| Blocking C call | `sum(range(10**8))`, a `re` match | one opaque C call charges no tick and holds the GIL, so the watchdog cannot preempt it; `run_guarded` gives up the join and the worker leaks until it finishes |
| Allocation outside `+`/`*`/`**` | `bytes(10**8)`, `list(range(10**8))`, `'%09999d' % 1` | `__sb_binop__` bounds only the three rewritten operators; a C-level constructor or `%` width allocates directly |
| Regex backtracking | `(a+)+` on a crafted subject | the engine backtracks in C, past `eval-timeout`, holding the GIL; the guard warns and suggests a linear engine (`re2`) but does not refuse |
| Interpreter escape | a CPython segfault | out of reach of any AST-level guard |

The leak counter (`eval-max-leaked-threads`) bounds how many such runaway
workers are tolerated before new evaluations are refused, turning an unbounded
CPU leak into an eventual, explicit refusal — but the real guarantee remains
the OS sandbox.

---

## Things that look like holes but are not

- **`type(x).mro()`** hands back the class objects of the MRO (including
  `object`) when `eval-attribute=mro` is granted — but every dangerous next hop
  (`__subclasses__`, `__bases__`, `__globals__`) is a dunder gated by
  `eval-magic`. It is an information disclosure at most, not an escape.
- **`with cm:`** invokes `cm.__enter__` / `__exit__` in C, bypassing
  `eval-magic`. This only matters for a context manager the application *chose*
  to pass through `names` — trusted data, like any callable the app provides. A
  context manager defined *inside* the evaluated code runs its `__enter__` under
  the guard like any other function body.
- **Wide `eval-magic=*` or `eval-attribute=*`** reopens the class-hierarchy
  walk. This is the grant doing exactly what it says — "opens the whole type
  hierarchy" is the warning the guard prints for it. It is a configuration
  choice, not a bypass.

---

## Reproducing the assessment

```bash
# the full attack matrix (blocked escapes + allowed payloads)
uv run pytest tests/unit_tests/guard/test_eval_attack_matrix.py -v

# per-rule hardening regressions
uv run pytest tests/unit_tests/guard/test_eval_hardening.py -v

# the escape corpus, each asserting the catching layer
uv run pytest tests/unit_tests/guard/test_eval_security_corpus.py -v
```

Bottom line: every attribute read passes through the single `_check_attr`
gate, whether by dot, by `getattr`/`vars`/`hasattr`, by `str.format` on an
instance or on the class, or by `string.Formatter`. Recursion by function, lambda
or generator is bounded by `eval-max-call-depth`. The only ways through
are denial of service, which the design states plainly are the OS layer's job.

## Recommendations

- Treat static validation as a courtesy to the rule author, never as a barrier: a dynamically built name is never seen.
- Grant capability builtins such as `getattr` with care: they hand back, by their own name, a door the bounded namespace had shut.
- Avoid wide grants such as `eval-magic=*` or `eval-attribute=*`: they reopen the class-hierarchy walk.
- Pass through `names` only trusted callables and context managers: the guard trusts them like any callable the application provides.
- Keep an OS sandbox around the evaluation: blocking C calls, allocations outside the rewritten operators and regex backtracking are stopped only there.

## References

- [The `eval-*` sub-language](eval.md)
- [Weaknesses](weaknesses.md)
