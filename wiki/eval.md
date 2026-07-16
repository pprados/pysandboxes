# Dynamically evaluated code — the `eval-*` rules

> **Status: specified, not yet implemented.** The rules described here are the
> agreed design for the `dynamic-code` guard. They do not exist in the shipped
> package yet. Until they do, `eval()`, `exec()` and `compile()` are *not*
> intercepted, and a string handed to them runs with the full rights of the
> sandboxed process.

`py-sandboxes` guards imports, files, sockets, environment variables and a
registry of sensitive functions. None of those layers looks at code that
arrives as a **string** at runtime.

That string is exactly what an LLM produces. A tool that does

```python
result = eval(expression, {"__builtins__": {}}, {})
```

is not protected by the emptied `__builtins__`: the payload below reaches
`Popen` without naming a single builtin.

```python
"[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/sh'])"
```

The `eval-*` rules describe a **sub-language**. A source that arrives at
`eval`, `exec` or `compile` is parsed, checked against that sub-language,
rewritten so the remaining risks are enforced while it runs, and executed
under a budget and a timeout the caller can recover from.

Only code reaching those three builtins is transformed. Your application's own
modules are untouched, and import time is unaffected.

---

## Table of contents

- [The three states of the guard](#the-three-states-of-the-guard)
- [Deny-all, and the minimal core](#deny-all-and-the-minimal-core)
- [How the rules combine](#how-the-rules-combine)
- [The five list keys](#the-five-list-keys)
  - [`eval-syntax`](#eval-syntax)
  - [`eval-call`](#eval-call)
  - [`eval-attribute`](#eval-attribute)
  - [`eval-import`](#eval-import)
  - [`eval-magic`](#eval-magic)
- [The eight scalar keys](#the-eight-scalar-keys)
  - [`eval-namespace`](#eval-namespace)
  - [`eval-timeout`](#eval-timeout)
  - [`eval-max-iterations`](#eval-max-iterations)
  - [`eval-max-call-depth`](#eval-max-call-depth)
  - [`eval-max-depth`](#eval-max-depth)
  - [`eval-max-nodes`](#eval-max-nodes)
  - [`eval-max-alloc`](#eval-max-alloc)
  - [`eval-max-leaked-threads`](#eval-max-leaked-threads)
- [Profiles](#profiles)
- [Error reporting](#error-reporting)
- [Learning mode](#learning-mode)
- [Profiles you can copy](#profiles-you-can-copy)
  - [1. Calculator tool](#1-calculator-tool)
  - [2. Data analysis over rows you supply](#2-data-analysis-over-rows-you-supply)
  - [3. Data analysis over a DataFrame](#3-data-analysis-over-a-dataframe)
  - [4. Row filter / predicate](#4-row-filter--predicate)
  - [5. Business rule engine](#5-business-rule-engine)
  - [6. Report and message templating](#6-report-and-message-templating)
  - [7. Agent-written snippet](#7-agent-written-snippet)
  - [8. Development escape hatch](#8-development-escape-hatch)
  - [Choosing between them](#choosing-between-them)
- [What this does not cover](#what-this-does-not-cover)

---

## The three states of the guard

`eval`, `exec` and `compile` join the sensitive-function registry under a new
`dynamic-code` category, so the guard has an effect whether or not you write a
single `eval-*` rule.

| Configuration | `eval()` behaviour |
|---|---|
| no `eval-*` key, no `python-api=ALLOW:dynamic-code` | **refused**, `RuleApiPermissionError` |
| at least one `eval-*` key | **guarded**: parsed, validated, rewritten, run under budget |
| `python-api=ALLOW:dynamic-code` | **unguarded**, an explicit escape hatch, warned like `process-exec` |

The last row wins over the middle one: a profile that carries both runs
unguarded. Writing that line is asking for the pre-guard behaviour, and a rule
that silently did something else would be the worst of both.

`ast.literal_eval` is not concerned: it evaluates literals only and constructs
no code object.

Code generation performed by the runtime itself — `dataclasses`,
`typing`, `collections`, `importlib`, and libraries installed in
`site-packages` — is exempt. Those call sites generate code structurally, not
on your behalf, and refusing them would mean no module could be imported at
all. Only your application's own call sites are guarded.

---

## Deny-all, and the minimal core

Like every other layer, the accepted language is a **whitelist**. With at
least one `eval-*` key present, what runs is the *minimal core* plus whatever
the keys open.

The minimal core is not expressible and not removable:

| Construct | Why it cannot be optional |
|---|---|
| `Module`, `Expression`, `Interactive` | the parse root |
| `Constant` | a literal is the smallest useful expression |
| `Name` read | reading a variable you provided |
| `Tuple`, `List`, `Dict`, `Set` literals | container literals |
| `Expr` | an expression used as a statement |

So `1 + 1` is **refused** until `eval-syntax=arith` is present. That inversion
is what the whole design rests on.

```ini
# Valid: a profile that evaluates literals and nothing else
eval-timeout=2s
```

```python
eval("[1, 2, 3]")   # OK — a container literal is in the core
eval("1 + 1")       # REFUSED — 'BinOp' is not allowed
```

---

## How the rules combine

Every list key accumulates into **two unordered sets**, allow and deny.
Repeating a key unions its values, so rule order carries no meaning and an
`include` cannot be defeated by placement.

One resolution rule: **`DENY:` wins, always, wherever it appears.** No
specificity comparison, no precedence table, no last-one-wins.

```ini
# Valid — these two lines mean the same thing in either order
eval-attribute=get*, is*
eval-attribute=DENY:get_secret
```

```ini
# Invalid — DENY: and patterns apply to list keys only
eval-timeout=DENY:5s
eval-namespace=adaptive*
```

**Patterns** use the same single-`*` glob as `env=`, and apply to every list
key except `eval-syntax`, whose vocabulary is finite and enumerated.

```ini
# Valid
eval-attribute=get*, to_*
eval-import=json.*
```

```ini
# Invalid — a pattern on a closed vocabulary only obscures it
eval-syntax=Bin*
```

A pattern is a silent error multiplier. Any pattern whose fixed part is
shorter than three characters, and any bare `*`, emits a configuration warning
naming what it expands to on the running interpreter:

```
eval-attribute=ge*  expands to 47 names on this interpreter, including
                    'get_secret' — narrow the pattern or add a DENY
```

---

## The five list keys

### `eval-syntax`

Which Python constructs the source may use. Accepts a **group** or the **exact
name of an `ast` node class**, mixed freely — the same shape as
`python-api=ALLOW:<category>` versus `ALLOW:os.system`.

| Group | Nodes |
|---|---|
| `arith` | `BinOp`, `UnaryOp` |
| `compare` | `Compare`, `BoolOp` |
| `conditional` | `If`, `IfExp` |
| `loop` | `For`, `While`, `Break`, `Continue` |
| `comprehension` | `ListComp`, `SetComp`, `DictComp`, `GeneratorExp`, `comprehension` |
| `assign` | `Assign`, `AugAssign`, `AnnAssign`, `NamedExpr` |
| `func` | `FunctionDef`, `Return`, `arguments`, `arg`, `Lambda` |
| `async` | `AsyncFunctionDef`, `Await`, `AsyncFor`, `AsyncWith` |
| `class` | `ClassDef` |
| `exception` | `Try`, `TryStar`, `Raise`, `ExceptHandler` |
| `context` | `With`, `withitem` |
| `import` | `Import`, `ImportFrom`, `alias` |
| `subscript` | `Subscript`, `Slice`, `Starred` |
| `fstring` | `JoinedStr`, `FormattedValue` |
| `yield` | `Yield`, `YieldFrom` |

Async is neither privileged nor special-cased: `eval-syntax=async` opens it,
its absence closes it, exactly like `loop`.

A new Python release that adds a node makes that node **refused by default** —
the safe direction.

```ini
# Valid — a group, and one extra node by name
eval-syntax=arith, compare, Lambda
```

```python
eval("(1 + 2) < 4")          # OK
eval("[x for x in (1, 2)]")  # REFUSED — 'ListComp' is not allowed
```

```ini
# Invalid — 'lop' is not a group and not an ast node
eval-syntax=lop
# error: unknown syntax token 'lop', closest known token is 'loop'
```

---

### `eval-call`

Which names the source may call, **and** what the namespace's `__builtins__`
is built from. The two are the same list on purpose: a name the code cannot
reach is a name it cannot call, whatever spelling it invents.

An empty `eval-call` is legal and coherent. CPython does *not* repopulate a
`__builtins__` key that is present but empty, so a call-free profile evaluates
arithmetic and comparison over the data you passed in — exactly the calculator
tool the samples ship.

```ini
# Valid
eval-syntax=arith, comprehension
eval-call=len, range, sum
```

```python
eval("sum([i for i in range(3)])")   # OK
eval("open('/etc/passwd')")          # REFUSED — call to 'open' is not allowed
```

```ini
# Invalid — eval-call names functions, never categories
eval-call=process-exec
```

---

### `eval-attribute`

Which **ordinary** attribute names the source may read. Deny-all applies here
too: without the key, `"ab".split()` fails until `split` is declared.

Enforced at runtime, not only statically: whatever syntax led to the attribute,
the read is checked as it happens.

| Group | Content |
|---|---|
| `str-methods` | public names of `str`, **minus `format` and `format_map`** |
| `list-methods`, `dict-methods`, `set-methods`, `tuple-methods` | public names of the type |
| `num-methods` | public names of `int` and `float` |
| `bytes-methods` | public names of `bytes` |
| `date-methods` | public names of `datetime.date`, `.time`, `.datetime`, `.timedelta` |

Groups are computed from the running interpreter, not hardcoded.

`format` and `format_map` are curated out of `str-methods` deliberately.
`"{0.__class__}".format(o)` resolves the attribute **in C, from the contents
of the string**: there is no `Attribute` node anywhere in that source, so
nothing can validate or rewrite it. It is the one place where the guard is
structurally blind rather than merely incomplete. Granting `format` by name
still works — and emits a strong warning.

Contrast the f-string spelling `f"{o.__class__}"`, which compiles to a real
attribute access and is validated normally. Same result to the eye, opposite
exposure.

```ini
# Valid
eval-syntax=arith
eval-attribute=str-methods, DENY:encode
```

```python
eval("'a b'.split()")     # OK
eval("'ab'.encode()")     # REFUSED — DENY wins
eval("x.__class__")       # REFUSED — a dunder needs eval-magic
```

```ini
# Invalid in practice, though it parses: this disarms the layer
eval-attribute=*
# warning: expands to every name on this interpreter
```

Writing that list by hand is impractical, and nobody should: **learning mode
writes it**, from the names the code actually touched.

---

### `eval-import`

Which modules the source may import. Requires `eval-syntax=import` to be able
to write an `import` statement at all.

```ini
# Valid
eval-syntax=arith, import
eval-import=json, math
```

```python
eval("__import__('math')")   # REFUSED — '__import__' is not in eval-call
exec("import math")          # OK
exec("import os")            # REFUSED — import 'os' is not allowed
                             #   ⚠ os exposes the process environment
```

```ini
# Invalid — a module list, not a path list
eval-import=/usr/lib/python3.13/json
```

---

### `eval-magic`

Which dunder names — `__name__`, `__doc__`, … — the source may use, as an
attribute or as an identifier. Everything matching `__*__` is refused unless
listed.

This key is **ergonomics, not a barrier**. The barrier is the runtime
attribute check, which refuses a dunder reached by any means. Do not assume
that because `eval-magic` exists, the runtime guard is redundant.

A closed set of frame-capture attributes is refused **even when
`eval-attribute` or `eval-magic` would allow them**: `gi_frame`, `gi_code`,
`gi_yieldfrom`, `cr_frame`, `cr_code`, `cr_await`, `ag_frame`, `ag_code`,
`f_globals`, `f_locals`, `f_builtins`, `f_back`, `f_trace`, `tb_frame`,
`tb_next`. A generator reaches the real globals through `gi_frame.f_globals`
without writing a single dunder, and no configuration should be able to open
that by accident. This is the one implicit, non-overridable `DENY`.

```ini
# Valid
eval-magic=__name__, __doc__
```

```python
eval("x.__name__")      # OK
eval("x.__class__")     # REFUSED — add eval-magic=__class__
                        #   ⚠ opens the whole type hierarchy
```

```ini
# Invalid — the __sb_ prefix is reserved for the guard's own helpers
eval-magic=__sb_getattr__
```

Any source mentioning `__sb_` is refused outright. Without that check,
`__sb_tick__ = lambda: None` disarms the interruption guard in one line.

---

## The eight scalar keys

Scalar values accept `_` as a digit separator, a decimal size suffix
(`KB`/`MB`/`GB`) and a duration suffix (`ms`/`s`/`m`). A repeated scalar key in
the same profile is a configuration error rather than a silent last-wins:
"the rules are a set" carries no meaning for a scalar, and a duplicate is
almost always a mistake.

---

### `eval-namespace`

Default `adaptive`. What happens to a context the application itself passed.

| Value | Behaviour |
|---|---|
| `adaptive` | honour a caller-supplied context, but never CPython's automatic builtin injection. Default |
| `closed` | ignore the caller's globals; the namespace comes from `eval-call` only. **Use for model output** |
| `caller` | honour everything the caller passed, injection included, and skip the rewrite. Debugging only |

Under `adaptive`:

| Call | Namespace used | Warning |
|---|---|---|
| `eval(e, {"__builtins__": {}}, {})` | the caller's, untouched | none |
| `eval(e, {"helper": f}, {})` | the caller's, plus `__builtins__` from `eval-call` | graded |
| `eval(e)` | built entirely from `eval-call` | none |

Row 2 is the important one. When you supply globals **without** a
`__builtins__` key, CPython injects all 159 builtins — so the author of
`eval(e, {"helper": f}, {})` believes they passed one helper and has in fact
passed `open`, `getattr` and `__import__`. That injection is never honoured in
`adaptive` or `closed`; the key is filled from `eval-call` instead.

Row 3 is a **deliberate behaviour change**. A bare `eval(e)` in plain Python
sees the caller's `globals()` *and* `locals()` plus the injected builtins:

```python
SECRET = "sensitive"

def caller():
    eval("SECRET")   # plain Python: "sensitive".  Guarded: NameError
```

Reading your whole module surface into a string evaluation is the exact hazard
this guard exists to address, so the break is the point. Pass what the
expression needs instead: `eval(e, {"SECRET": SECRET}, {})`, which `adaptive`
honours untouched.

Each graded name in a supplied context emits a `SandboxContextWarning`, once
per call site:

| What is passed | Level |
|---|---|
| a module (`os`, `sys`, …) | strong |
| a capability builtin: `getattr`, `setattr`, `open`, `eval`, `exec`, `compile`, `__import__`, `type`, `vars`, `globals`, `dir`, `breakpoint` | strong |
| a callable whose module is `os`, `subprocess`, `importlib`, `ctypes`, `socket` | strong |
| any other callable, or any other instance | weak |
| scalars and containers of scalars | none |

```
SandboxContextWarning: eval() context provides module 'os' at tools.py:66
    the evaluated code can reach everything it exposes
    acknowledge with: eval-call=os        (or use eval-namespace=closed)
```

It is a `warnings.warn`, not a log line, so your project decides: promote with
`-W error::SandboxContextWarning`, silence per module with `filterwarnings`,
or assert on it with `pytest.warns`.

```ini
# Valid — the recommended setting for a tool handling model output
eval-namespace=closed
eval-syntax=arith, compare
```

```ini
# Invalid
eval-namespace=open
# error: unknown mode 'open', expected one of ['adaptive', 'closed', 'caller']
```

**The price of `adaptive`, stated:** the configuration file no longer
describes the whole reachable surface on its own — an audit must also read the
call sites. That is why the mode is a named key rather than implicit
behaviour, and why a profile handling model output should set `closed`.

---

### `eval-timeout`

Default `5s`. Wall-clock time before the evaluation is interrupted. The code
runs in a dedicated thread; the interruption reaches the caller as
`EvalInterrupted`.

`EvalInterrupted` derives from `BaseException` **only**, and the exclusion is
load-bearing: every other sandbox exception is a `RuntimeError`, so a bare
`except Exception:` inside the evaluated code — reachable as soon as
`eval-syntax=exception` opens `try` — would swallow its own interruption.

Consequence for your code: **`except SandBoxError:` does not catch a timeout.**

```ini
# Valid
eval-timeout=2s
eval-timeout=250ms
```

```python
from pysandboxes import EvalInterrupted

try:
    exec("while True: pass", {"__builtins__": {}}, {})
except EvalInterrupted as err:
    print("interrupted:", err.reason)
```

```ini
# Invalid — a size suffix on a duration
eval-timeout=10MB
```

---

### `eval-max-iterations`

Default `1_000_000`. How many loop and comprehension iterations the source may
consume. The name says what it measures: straight-line code and a lone
`10**9` consume none — those are the job of the allocation check and of the
timeout.

```ini
# Valid
eval-max-iterations=100_000
```

```python
exec("while True:\n    pass")   # EvalInterrupted: eval-max-iterations=100000
```

```ini
# Invalid — a duration suffix on a count
eval-max-iterations=5s
```

---

### `eval-max-call-depth`

Default `20`. Runtime call depth of functions defined inside the evaluated
code.

It exists because the iteration budget does **not** bound recursion: a
recursive function consumes no iteration, so without this it would run to
CPython's own `RecursionError` — which is an `Exception`, and therefore
catchable by the evaluated code itself.

```ini
# Valid
eval-syntax=func
eval-max-call-depth=10
```

```python
exec("def f(n):\n    return f(n + 1)\nf(0)")
# EvalInterrupted: eval-max-call-depth=10
```

```ini
# Invalid — this is the runtime depth, not the static one
eval-max-call-depth=20KB
```

---

### `eval-max-depth`

Default `20`. **Static** AST nesting accepted before the code runs. Distinct
from `eval-max-call-depth`: this one bounds a deeply nested literal that would
blow the stack inside the parser itself.

```ini
# Valid
eval-max-depth=20
```

```python
eval("[" * 5000 + "]" * 5000)   # refused before execution
```

---

### `eval-max-nodes`

Default `5_000`. Static node count of the parsed source. A cheap ceiling on
how much code a single string may carry.

```ini
# Valid
eval-max-nodes=500
```

```python
eval("[" + ", ".join("1" for _ in range(10_000)) + "]")
# refused: the source holds 10002 nodes
```

---

### `eval-max-alloc`

Default `10MB`. Bound on what the rewritten operators may allocate. `**`, `*`
and `+` are checked **before** the operation, because the damage is done
inside C otherwise.

```ini
# Valid
eval-max-alloc=1MB
```

```python
eval("10 ** 10**9")   # refused before computing — would hang CPython in C
eval("[0] * 10**10")  # refused before allocating
eval("2 ** 8")        # OK
```

This bounds the operators, not the process: a native library allocating
internally passes through no check.

---

### `eval-max-leaked-threads`

Default `4`. How many uncooperative workers are tolerated before new
evaluations are refused.

A blocking C call — catastrophic backtracking in `re`, a native library —
never returns to a check point. The caller gets its `EvalInterrupted` and
**the thread keeps burning CPU**, cumulatively across calls. Counting them and
refusing beyond a threshold is a mitigation; the real guarantee is the OS
layer, where a timeout is a process kill.

```ini
# Valid
eval-max-leaked-threads=2
```

---

## Profiles

A `:name` suffix defines a **complete, independent** profile. There is no
inheritance from the default one.

```ini
# Valid
eval-syntax=arith, compare, loop
eval-timeout=5s

eval-syntax:llm=arith
eval-timeout:llm=2s
eval-namespace:llm=closed
```

```python
from pysandboxes import guarded_eval

result = guarded_eval(expression, profile="llm", names={"data": rows})
```

Independence is what lets a call site **restrict**. Under inheritance a
profile could only widen the default — a union of sets admits no subtraction —
and hardening at the call site would be impossible. The cost is duplication
between similar profiles, accepted.

A profile named in a call but absent from the configuration is an error at
call time, never a silent fallback to the default.

`guarded_eval` is a different entry point from the patched builtin:
`eval-namespace` does not apply to it, because choosing it is itself the
statement of intent. Its `names` argument is data merged into a namespace
built from `eval-call`, never used in place of one.

---

## Error reporting

One report, every violation, each naming the rule that would allow it.

```
EvalSyntaxRejected: 3 rules violated in <eval:llm>

  line 2, col 4: 'While' is not allowed
      while True:
      ^^^^^^^^^^^
    add: eval-syntax=loop        (or, narrower: eval-syntax=While)

  line 3, col 8: import 'os' is not allowed
          import os
          ^^^^^^^^^
    add: eval-import=os          ⚠ os exposes the process environment

  line 5, col 12: attribute '__class__' is not allowed
          return x.__class__
          ^^^^^^^^^^^^^^^^^^
    add: eval-magic=__class__    ⚠ opens the whole type hierarchy
```

Three properties:

- **exhaustive** — a model correcting its own code converges in one round
- **actionable** — the exact line to paste into `.py-sandboxes`
- **honest** — a warning where granting the rule is a real widening

`EvalSyntaxRejected` is both a `SandBoxError` and a `SyntaxError`, so editors
and tracebacks render its `lineno`, `offset` and `text` the way they already
do.

---

## Learning mode

Learning happens at `eval()` invocation, like every other guard. Violations
are recorded instead of raised, the code runs with the widened set, and the
lines land in the `<learning_guard_eval>` block:

```ini
# <learning_guard_eval>
# Add rules (2026/09/10 at 14:22)
eval-syntax=arith, compare, loop, comprehension
eval-call=len, range, sum
eval-attribute=split, join, strip                    # ⚠ runtime-observed
eval-magic=__name__
# </learning_guard_eval>
```

Two emission rules worth knowing:

- a group replaces its nodes **only when every node of that group was
  observed**, so learning never grants more than it saw;
- **never a pattern**. Generalising from a sample is precisely what learning
  must not do.

When `adaptive` honoured a caller-supplied context, `eval-call` was never
consulted for the namespace, so emitting it would produce rules that are at
once unused and misleading. The block carries a comment instead:

```ini
# eval-call not emitted: the namespace came from the call site
#   (tools.py:66). Set eval-namespace=closed to declare it here.
```

That comment doubles as the migration prompt towards `closed`.

---

## Profiles you can copy

Eight starting points, ordered from the narrowest to the widest. Each is a
complete profile: paste it into `.py-sandboxes`, then narrow it with learning
mode against your own corpus.

All eight set `eval-namespace=closed`. Anything that evaluates a model's
answer should: `adaptive` exists so an existing caller keeps working, not
because it is the right posture for model output.

---

### 1. Calculator tool

The tool every agent framework ships. The model returns `"40 + 2"` or
`"(3 + 4) * 2"`, and nothing else should ever run.

```ini
eval-namespace=closed
eval-syntax=arith, compare
eval-max-iterations=100_000
eval-timeout=2s
```

No `eval-call`, and that is not an oversight: arithmetic over literals needs
no function at all, so `__builtins__` stays empty and no spelling reaches
`open` or `__import__`.

```python
guarded_eval("(3 + 4) * 2")                      # 14
guarded_eval("2 ** 10")                          # 1024
guarded_eval("len([1, 2])")                      # REFUSED — eval-call=len
guarded_eval("().__class__.__base__")            # REFUSED — eval-magic=__class__
guarded_eval("10 ** 10**9")                      # REFUSED — eval-max-alloc
```

Add `eval-call=round, abs, min, max` the day the model starts writing
`round(1/3, 2)`. Learning mode will tell you.

---

### 2. Data analysis over rows you supply

The common "ask the model to compute a metric" case. The host fetches the
data, hands it over as plain Python, and the model writes the aggregation.

```python
rows = [{"region": "EU", "amount": 120.0}, {"region": "US", "amount": 80.0}]
answer = guarded_eval(model_expression, profile="analysis", names={"rows": rows})
```

```ini
eval-namespace:analysis=closed
eval-syntax:analysis=arith, compare, comprehension, conditional, subscript
eval-call:analysis=len, sum, min, max, abs, round, sorted, any, all, set, list, dict
eval-max-iterations:analysis=1_000_000
eval-max-alloc:analysis=50MB
eval-timeout:analysis=5s
```

```python
# OK
"sum(r['amount'] for r in rows if r['region'] == 'EU')"
"round(sum(r['amount'] for r in rows) / len(rows), 2)"
"sorted({r['region'] for r in rows})"
"max(r['amount'] for r in rows) if rows else 0"

# REFUSED
"[r for r in rows if r.get('region') == 'EU']"   # eval-attribute=get
"__import__('os').listdir('.')"                  # '__import__' not callable
"open('/etc/passwd').read()"                     # 'open' not callable
"[0] * 10**10"                                   # eval-max-alloc
```

Note what the third refusal teaches: the moment the model writes `.get(...)`
instead of `[...]`, you need `eval-attribute=get`. Two spellings of the same
intent, one of which costs a rule. Run learning mode over a representative
sample of model answers rather than guessing which one it prefers — and grant
the method names one by one:

```ini
eval-attribute:analysis=get, items, keys, values
```

Deny-all on attributes is what makes this profile safe to hand a live object
instead of a copy. Without it, `conn.execute("DROP TABLE")` would traverse the
guard untouched.

---

### 3. Data analysis over a DataFrame

Same shape, but the object you pass carries hundreds of methods, so
`eval-attribute` becomes the load-bearing key rather than an afterthought.

```python
answer = guarded_eval(model_expression, profile="frame", names={"df": df})
```

```ini
eval-namespace:frame=closed
eval-syntax:frame=arith, compare, subscript, conditional
eval-call:frame=len, round, min, max, sum, list
# A list key may be repeated: the values are unioned, so a long allow list
# splits across as many lines as it needs and their order carries no meaning.
eval-attribute:frame=groupby, agg, mean, median, sum, count, nunique
eval-attribute:frame=min, max, std, describe, head, tail, sort_values
eval-attribute:frame=value_counts, dropna, fillna, columns, shape, loc, iloc
eval-attribute:frame=DENY:to_*, read_*, apply, pipe, eval, query
eval-max-alloc:frame=200MB
eval-timeout:frame=10s
```

```python
# OK
"df[df['region'] == 'EU']['amount'].sum()"
"df.groupby('region')['amount'].mean()"
"round(df['amount'].std(), 2)"

# REFUSED
"df.to_csv('/tmp/leak.csv')"       # DENY:to_* — writing is not analysing
"df.apply(lambda r: __import__)"   # DENY:apply — it runs arbitrary callables
"df.query('amount > 0')"           # DENY:query — a second expression engine,
                                   #   outside this guard entirely
```

Three things worth knowing before shipping this one:

- **Pass the object, never the module.** `names={"pd": pandas}` under
  `adaptive` raises a strong `SandboxContextWarning`, and rightly:
  `pd.read_csv` reaches the filesystem. Under `closed` the module simply is
  not there.
- **`DENY:` earns its keep here.** The allow list is long enough that an
  exhaustive one is unmaintainable; denying the `to_*` and `read_*` families
  and the three callable-taking methods is shorter and ages better.
- **`eval-max-alloc` does not bound pandas.** It checks the `+`, `*` and `**`
  the evaluated source writes; a join performed inside the library allocates
  through no check of ours. The OS layer is what bounds that.

---

### 4. Row filter / predicate

A model turning "customers in France over 18" into a boolean expression, one
row at a time. The narrowest useful profile there is.

```ini
eval-namespace:filter=closed
eval-syntax:filter=compare, subscript
eval-max-nodes:filter=200
eval-timeout:filter=1s
```

Empty `eval-call`, empty `eval-attribute`, no arithmetic: a predicate that
needs to call something is a predicate that has grown into a program.

```python
# OK
"row['age'] >= 18 and row['country'] in ('FR', 'BE')"
"row['status'] != 'closed'"

# REFUSED
"len(row['tags']) > 0"        # eval-call=len
"row['name'].startswith('A')" # eval-attribute=startswith
"row['a'] + row['b'] > 10"    # eval-syntax=arith
```

Each refusal is a deliberate design question, not an obstacle: if the model
keeps reaching for `startswith`, granting it is one line — and now that grant
is visible in the profile instead of buried in a helper.

---

### 5. Business rule engine

Pricing, scoring, eligibility: rules a business user writes and a model may
draft, evaluated against named values the host supplies.

```ini
eval-namespace:rules=closed
eval-syntax:rules=arith, compare, conditional
eval-call:rules=min, max, round, abs
eval-max-nodes:rules=500
eval-timeout:rules=1s
```

```python
guarded_eval(rule, profile="rules", names={"amount": 250.0, "tier": "gold", "years": 4})

# OK
"round(amount * (0.15 if tier == 'gold' else 0.05), 2)"
"min(amount * 0.2, 100.0)"
"0 if years < 1 else min(years * 5, 25)"

# REFUSED
"[amount for _ in range(10**9)]"   # eval-syntax=comprehension
"amount if amount else exit()"     # 'exit' not callable
```

No loops, no comprehensions, no function definitions: a rule that needs them
is no longer a rule. Keeping the vocabulary this small is also what makes the
profile readable to the non-programmer who owns the rules.

---

### 6. Report and message templating

A model composing a sentence from values you supply.

```ini
eval-namespace:template=closed
eval-syntax:template=fstring, arith, compare, conditional
eval-call:template=round, len, str, int, float
eval-attribute:template=upper, lower, title, strip, replace, split, join
eval-timeout:template=1s
```

```python
# OK
'f"{name.title()}: {total:.2f} EUR"'
'f"{len(items)} item" + ("s" if len(items) > 1 else "")'

# REFUSED
'"{0.__class__}".format(obj)'     # 'format' is not in str-methods
```

That last refusal is the point of this profile's shape. `str.format` resolves
attributes **in C, from the contents of the string**, so no node exists to
validate — the guard is structurally blind to it. It is curated out of
`str-methods` for exactly that reason, and the f-string spelling, which
compiles to a real attribute access and *is* checked, is the one to use. See
[`eval-attribute`](#eval-attribute).

Granting `eval-attribute:template=format` works and emits a strong warning.
Do it only if the templates come from a trusted author.

---

### 7. Agent-written snippet

The widest profile that still deserves the name. An agent writes a few lines
of real Python — loops, a helper function, a try block — over data you
supplied.

```ini
eval-namespace:agent=closed
eval-syntax:agent=arith, compare, conditional, loop, comprehension
eval-syntax:agent=assign, func, subscript, fstring, exception
eval-call:agent=len, sum, min, max, abs, round, sorted, enumerate, zip, range
eval-call:agent=any, all, list, dict, set, tuple, str, int, float, bool
eval-attribute:agent=str-methods, list-methods, dict-methods
eval-max-iterations:agent=500_000
eval-max-call-depth:agent=15
eval-max-nodes:agent=2_000
eval-max-alloc:agent=20MB
eval-timeout:agent=10s
```

```python
# OK
"""
totals = {}
for r in rows:
    totals[r['region']] = totals.get(r['region'], 0) + r['amount']
result = sorted(totals.items())
"""

# REFUSED
"import os"                        # eval-syntax=import, then eval-import=os
"class C: pass"                    # eval-syntax=class
"def f(n): return f(n+1)"          # runs, then eval-max-call-depth=15
"while True: pass"                 # runs, then eval-max-iterations
```

Two notes on the budgets, which matter more here than anywhere else:

- `eval-max-call-depth` is what stops runaway recursion. The iteration budget
  does not see it, and CPython's own `RecursionError` is an `Exception` that
  the snippet can catch itself now that `exception` is open.
- `eval-timeout` reaches the caller as `EvalInterrupted`, which derives from
  `BaseException` only — so a bare `except Exception:` in the snippet cannot
  swallow its own interruption, and **your** `except SandBoxError:` will not
  catch it either.

If a snippet at this width needs `import`, prefer granting the module through
`names=` as an already-configured object over opening `eval-syntax=import`.
You keep control of what the object is.

---

### 8. Development escape hatch

For a debugging session, and for nothing that ships.

```ini
# Unguarded: the source is not parsed, not checked, not rewritten.
python-api=ALLOW:dynamic-code
```

or, to keep the guard registered but honour whatever the call site passes,
injection included:

```ini
eval-namespace=caller
eval-syntax=arith
```

Both are warned at load like `process-exec`. `caller` also skips the rewrite —
honouring CPython's automatic builtin injection and running the guarded
helpers are mutually exclusive — so nothing in this row protects anything.
Reach for it when you are diagnosing the guard itself, never to make a failing
profile pass.

---

### Choosing between them

| Profile | `eval-call` | `eval-attribute` | Functions & loops | Typical timeout |
|---|---|---|---|---|
| 1. Calculator | — | — | no | 2s |
| 2. Rows | a dozen builtins | a few, learned | no | 5s |
| 3. DataFrame | a few builtins | long, with `DENY:` families | no | 10s |
| 4. Predicate | — | — | no | 1s |
| 5. Rules | 4 numeric builtins | — | no | 1s |
| 6. Templating | 5 conversions | `str` methods | no | 1s |
| 7. Agent snippet | ~20 builtins | 3 type groups | yes | 10s |
| 8. Escape hatch | *unguarded* | *unguarded* | *unguarded* | *none* |

Start one row narrower than you think you need. A refusal names the exact
line to add, so widening costs one paste; discovering months later that a
profile was wider than the task required costs an audit.

---

## What this does not cover

Stated plainly so no one reads more into the guard than it offers.

- **Blocking C calls.** Catastrophic backtracking in `re`, a native library:
  none returns to a check point. Mitigated by
  [`eval-max-leaked-threads`](#eval-max-leaked-threads), guaranteed only by
  the OS layer.
- **Memory outside the rewritten operators.** `eval-max-alloc` bounds `+`, `*`
  and `**`, not the process.
- **CPython bugs.** A segfault or an interpreter escape is out of reach of any
  AST-level guard.
- **Side effects of allowed calls.** If `eval-call` grants a function that
  opens files, the file rules apply — but this guard adds nothing.
- **Timing and side channels.**
- **`str.format` and `format_map`.** The attribute is resolved in C from the
  contents of a string, so no node exists to validate or rewrite. Handled by
  curating them out of `str-methods`, which is a mitigation, not a fix.
- **Audit from the configuration alone**, under `eval-namespace=adaptive`: the
  reachable surface is the configuration *plus* what each call site passes.
  `closed` restores the property, at the cost of declaring every name.
- **Code generation by a third-party library outside `site-packages`** — a
  vendored `attrs`, a source checkout on `PYTHONPATH`. The ambient exemption
  is path-based, so such a library is guarded like application code and its
  generated function will be refused. `python-api=ALLOW:dynamic-code` is the
  escape hatch.

---

See also: [weaknesses](weaknesses.md) · [implementation](implementation.md) ·
[roadmap](roadmap.md)
