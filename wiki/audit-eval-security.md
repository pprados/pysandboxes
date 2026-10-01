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

Every attack below is pinned as an executable test in
`tests/unit_tests/guard/test_eval_attack_matrix.py` (blocked attacks and
allowed payloads) and `tests/unit_tests/guard/test_eval_hardening.py`
(per-rule regression). If a payload ever changes column, a test changes with
it.

---

## Table of contents

- [The threat model in one paragraph](#the-threat-model-in-one-paragraph)
- [Three layers, two of which enforce](#three-layers-two-of-which-enforce)
- [The master lever: capability builtins](#the-master-lever-capability-builtins)
- [Attack matrix — escapes that are blocked](#attack-matrix--escapes-that-are-blocked)
- [Attack matrix — payloads that still run](#attack-matrix--payloads-that-still-run)
- [The `str.format` blind spot, and how it was closed](#the-strformat-blind-spot-and-how-it-was-closed)
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
route around; the namespace and the runtime helpers are the real barriers.**
The hardening described here removed the known ways to reach an attribute
*without* going through `_check_attr`, except `string.Formatter` (see
[the `str.format` section](#the-strformat-blind-spot-and-how-it-was-closed)).

---

## The master lever: capability builtins

A handful of builtins hand back, *by their own name*, a door the bounded
namespace had shut. The sharpest is `getattr`: the raw builtin reads any
attribute in C, so binding it unguarded reopened `eval-magic`, `eval-attribute`
**and** the frame-capture DENY at once.

```python
# with eval-call=getattr and nothing else, the raw builtin was a full escape:
getattr((), '__class__')                       # -> <class 'tuple'>   (eval-magic bypassed)
getattr(getattr(gen, 'gi_frame'), 'f_globals') # -> real globals      (FRAME_CAPTURE bypassed)
```

These builtins are now **bound under their own name to a guarded shim**, so
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
now also logs a warning at configuration-parse time.

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

## The `str.format` blind spot, and how it was closed

`str.format` resolves `{0.__class__}` **in C**, from the contents of the
string. No `Attribute` node exists for static validation or for
`__sb_getattr__` to see — so `format` was a structural blind spot, curated out
of `str-methods` by default and only grantable with a warning.

The guard now **validates the template at runtime**. When `eval-attribute`
grants `format`, `__sb_getattr__` does not return the raw bound method; it
returns a wrapper that walks every field of the template with
`_string.formatter_field_name_split`, runs each attribute access through
`_check_attr`, and only then delegates to the real method. Index access
(`{0[0]}`) is data and left alone; nested spec fields (`{0:{1.__class__}}`) are
walked in turn.

A subtle second door — reaching the method through the **class** rather than an
instance — was found and closed during this assessment:

```python
str.format('{0.__class__}', ())        # unbound: template is the first argument
type('').format('{0.__class__}', ())   # same, reached through type()
```

The instance wrapper did not cover these, because the object to the left of the
dot is the `str` *class*, not a string. Both are now validated by an unbound
wrapper (`_guarded_format_unbound`), which also covers `str` subclasses.

A third door is **still open**: `string.Formatter`. Its `format`, `vformat`
and `get_field` resolve the same fields in Python (`getattr` in
`Formatter.get_field`), and `__sb_getattr__` wraps `format` only when the
object is a `str` or a `str` subclass:

```python
F.format('{0.__class__.__base__}', ())   # names={"F": string.Formatter()}, eval-attribute=format
# -> <class 'object'>
```

The same holds with `eval-import=string`, `eval-call=Formatter,__import__`
and `eval-attribute=Formatter,format`. Until the guard covers it, a
`Formatter` must not be handed to evaluated code, nor its methods granted.

---

## Lambdas and the call-depth budget

A `FunctionDef` body is rewritten with an inline `__sb_enter__()` /
`try … finally __sb_leave__()` bracket, so recursion charges a call frame and
is bounded by `eval-max-call-depth`. A **lambda** body is a single expression
that admits no statement, so before the hardening a lambda charged no frame:

```python
(lambda g: g(g))(lambda f: f(f))   # was: RecursionError (max-call-depth ignored)
```

Lambdas are now wrapped at definition — `_Injector.visit_Lambda` rewrites
`lambda … : body` into `__sb_func__(lambda … : body)`, and `__sb_func__`
brackets every call with enter/leave. Lambda recursion is now bounded exactly
like a function, raising `EvalInterrupted(eval-max-call-depth)` instead of a
catchable `RecursionError`. Generator recursion (`yield from`) was checked and
is already bounded, because the inline bracket's `__sb_enter__` runs on each
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

# the original escape corpus, each asserting the catching layer
uv run pytest tests/unit_tests/guard/test_eval_security_corpus.py -v
```

Bottom line: every attribute read — by dot, by `getattr`/`vars`/`hasattr`, by
`str.format` on an instance or on the class — now passes through the single
`_check_attr` gate, and recursion by function, lambda or generator is bounded
by `eval-max-call-depth`. One escape remains open, `string.Formatter`, and only
when the profile or the application hands it to the evaluated code; the other
remaining ways through are denial of service, which the design states plainly
are the OS layer's job.
