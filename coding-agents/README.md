# PySandboxes skills for coding agents

A coding-agent package for working with PySandboxes rule files. It contains two workflow skills:

- [`pysandboxes-rules-from-tests/SKILL.md`](pysandboxes-rules-from-tests/SKILL.md) guides full and
  partial test-based learning, separates application rules from test-runner and test-data rules, and requires
  human approval before promotion;
- [`pysandboxes-review-rules/SKILL.md`](pysandboxes-review-rules/SKILL.md) classifies rule changes
  before commit or merge and requires explicit approval before promotion or merging into the target branch;
The skills do not grant permissions or enforce Git operations. They guide the agent to show the proposed rules,
wait for human approval before changing active profiles, rerun tests strictly, and request a separate review and
approval before merging rules into the main branch. The learning and rule-grading commands remain tools in the
PySandboxes CLI; deleting the `python-sb` skill does not remove that CLI.

[`ci/sandbox-rules-review.yml`](ci/sandbox-rules-review.yml) is a GitHub workflow to copy into a project: on a pull
request that changes a `.py-sandboxes` file, it posts the graded table of the added rules. Pin the `ref` of the
pysandboxes checkout it holds to a release tag or a commit.

### AI pull-request reviewers

The workflow runs no model: its table is the same on every run. An AI reviewer can then explain each added rule,
with the code that needs it. [`ci/REVIEW_INSTRUCTIONS.md`](ci/REVIEW_INSTRUCTIONS.md) holds one paragraph for that,
the same for every reviewer; paste it into the file your reviewer reads.

| Reviewer                  | Status   | File                                                                 | Documentation                                                                                   |
|---------------------------|----------|----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| GitHub Copilot review     | untested | `.github/copilot-instructions.md`, or `AGENTS.md` at the root        | [use code review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review) |
| Codex (`@codex review`)   | untested | `AGENTS.md`, under a `## Code Review Rules` section                  | [AGENTS.md](https://developers.openai.com/codex/guides/agents-md), [GitHub](https://developers.openai.com/codex/integrations/github) |
| Claude Code Review        | untested | `REVIEW.md` at the root (`CLAUDE.md` findings are nits only)         | [code review](https://code.claude.com/docs/en/code-review)                                       |
| Claude Code GitHub Action | untested | `CLAUDE.md`                                                          | [GitHub Actions](https://code.claude.com/docs/en/github-actions)                                 |
| Gemini Code Assist        | untested | `.gemini/styleguide.md`                                              | [customize the review](https://docs.cloud.google.com/gemini/docs/code-review/customize-repo-review) |

Copilot reads the file from the branch of the pull request, so a pull request can change the instructions that
review it; the others do not say. None of the Anthropic or Google documentation mentions `AGENTS.md`.

## Install

Install the two shared skills from GitHub with the [Skills CLI](https://skills.sh/docs/cli):

```bash
npx skills add pprados/pysandboxes/coding-agents --skill '*'
```

The CLI prompts for the supported coding agent and installs the skills for the current project by default. Add
`--global` to install them for the current user. Reload the agent if it does not discover the skills immediately.
