# PySandboxes skills for coding agents

The PySandboxes coding-agent package contains two skills for discovering and reviewing permissions from tests.
They are instructions for the agent; they do not sandbox the agent's shell commands or enforce Git operations.

These animations are scripted illustrations, not recordings of live agents.

### Full mode

![Full mode: pytest runs inside python-sb; runner and application candidates are separated](../coding-agents/demo/coding-agents-full.gif)

The full-mode example captures an empty-test baseline, compares it with test learning, keeps runner permissions in
`.py-sandboxes.tests`, and proposes only application permissions for `.py-sandboxes`.

### Partial mode

![Partial mode: pytest stays on the host and only the @sandbox call learns](../coding-agents/demo/coding-agents-partial.gif)

The partial-mode example runs pytest on the host, learns from one marked test that calls `@sandbox`, and keeps only
the application candidates for review. It does not run `python-sb -m pytest`, which would move pytest into the
sandbox and demonstrate full mode instead.

## What the skills do

| Skill | Use it to |
|---|---|
| [`pysandboxes-rules-from-tests`](../coding-agents/pysandboxes-rules-from-tests/SKILL.md) | Choose full or partial mode, learn from tests, and classify candidates as application, test-runner/plugin, test-data, shared, or unclear. |
| [`pysandboxes-review-rules`](../coding-agents/pysandboxes-review-rules/SKILL.md) | Compare rule changes with the target branch, assess risk and scope, and tie each permission to code evidence. |

The skills help the agent follow a repeatable review. They do not automatically run learning, grant permissions,
or merge a branch. The learning skill asks before each permissive learning run and before changing active rule
profiles. Learning records accesses rather than refusing them, so run only trusted code; it does not provide an OS
sandbox boundary.

## Why keep test and application rules separate?

Both modes use `.py-sandboxes` for application runtime permissions and `.py-sandboxes.learn` for temporary
learning candidates. Full mode also uses `.py-sandboxes.tests` because pytest itself runs in the sandbox. Pytest
and application permissions are mixed during a full-suite capture, so compare it with an empty-test baseline,
inspect call sites, and promote only rules that belong in an active profile.

In partial mode, pytest stays on the host and only functions decorated with `@sandbox` run inside PySandboxes. The
test runner's host-side imports and fixture setup are not learned. Follow the test into the sandboxed function and
the modules it calls; a function-local or transitive application import can still require a rule in
`.py-sandboxes`. Python's standard-library `ast` module can inventory test imports at module and function scope,
but source and call-path evidence determine ownership.

Permission candidates for external access come from tests that exercise those interactions, typically integration
tests that perform real network or filesystem operations. Unit tests that mock those interactions do not execute
the external access and therefore cannot reveal the corresponding sandbox rules.

See [Can the test suite feed the learning mode?](faq.md#can-the-test-suite-feed-the-learning-mode) for the setup,
profiles, examples and strict verification for both modes.

## Example interaction

On a feature branch, an agent can be asked:

> Run the tests in the sandbox.

After learning, the agent should distinguish the permissions required by the sandboxed application path from
pytest or test-data permissions. It should show narrow candidates and any proposed adjustments, then wait for the
human decision. Once approved, run the full suite strictly. In partial mode, compare the candidate file before and
after one marked test at a time; pytest stays on the host, so only the code reached through `@sandbox` contributes
rules. In full mode, keep `.py-sandboxes.learn` separate from `.py-sandboxes` and `.py-sandboxes.tests`, and
compare full-suite candidates with an empty-test baseline.

Before a commit that changes active rules, and again before merging into the main branch, invoke
`pysandboxes-review-rules`. Compare the branch with the current target, explain and justify each difference, and
wait for explicit human approval. Approval to run learning or implement code is not approval to promote rules or
merge. If the review finds an overbroad or unexplained rule, narrow or remove it and present the updated diff for
approval. A project may separately require approval for every commit; these skills specifically gate rule
promotion and the merge into the target branch.

## Install

The two skills can be installed into supported coding agents with the Skills CLI. The package does not install a
Python-command hook.

The [Skills CLI](https://skills.sh/docs/cli) can install these two skills directly from the public repository. It
requires Node.js with `npx`; select the target coding agent when prompted:

```bash
npx skills add pprados/pysandboxes/coding-agents --skill '*'
```

By default, the CLI installs skills for the current project. Add `--global` to install them for the current user
instead. An agent may require a reload before it discovers newly installed skills.

After installation, ask the agent to list the available skills or invoke `pysandboxes-rules-from-tests` by name, or ask to execute a test, commit or merge.
If a skill is not discovered, verify the target directory and restart or reload the agent as its documentation
requires.
