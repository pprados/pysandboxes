# OWASP LLM
https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/

# Understanding the Attack Surface
By design, MCP enables LLMs to:

- Execute commands
- Access data
- Leverage multiple third-party tools
This introduces multiple potential vulnerabilities across the communication chain from the MCP Host → Client → Server, including any connected resources.


Key security risks (based on the OWASP Top 10 for LLM Applications):
- LM01: Prompt Injection — Malicious prompts can bypass filters and trigger unintended actions.
- LLM02: Insecure Output Handling — Raw, sensitive data (e.g., credentials) can be leaked.
- LLM04: Model DoS — Heavy prompts can overwhelm and crash systems.
- LLM05: Supply Chain Vulnerabilities — Malicious packages can be introduced via unverified MCP servers/tools.
- LLM06: Information Disclosure — Revealing server details can aid attackers.
- LLM09: Overreliance on AI — Unreviewed automation can lead to dangerous outcomes.

TODO: https://xxradar.medium.com/the-security-risks-of-model-context-protocol-mcp-c50c4817e80e

Practical Exploitation: Real-World Risks
Security testing has already uncovered concrete, dangerous vulnerabilities in existing MCP implementations, including:

**Path Traversal**: Reading arbitrary files on the server (e.g., /etc/passwd) is possible through poorly controlled access.

**Remote Code Execution (RCE)**: Tricking an LLM into running system commands (like whoami) can give attackers control over the machine.

**Reverse Shells**: An LLM can be manipulated into executing commands that open a remote shell to the attacker’s machine.

**SQL Injection**: MCP tools that interact with databases can be exploited to return unauthorized data.

**Lateral Movement**: If a public-facing MCP server is compromised, it can act as a proxy to access internal MCP servers, allowing attackers to bridge isolated systems.


Prompt Injection: Modifying model behavior through inputs.
Tool Poisoning: Hidden malicious instructions in tool descriptions.
Excessive Permissions: Overly powerful tools without proper checks.
Rug Pull Attacks: Tool definitions that change silently after approval.
Tool Shadowing: Malicious servers intercepting or overriding trusted tool calls.
Indirect Prompt Injection: Injected malicious data from external sources.
Token Theft: Weak storage leading to stolen authentication credentials.
Remote Access: Gaining control of host systems through misused tools.
Multi-Vector Attacks: Chaining several vulnerabilities for complex exploits.

# FAQ

## Comment propager un token à une api dans la sandbox ?
Remplacer:
```python
def call_llm():
  ...
```
par

```python
import os
from functools import partial

def _call_llm(token: str):
    ...


call_llm = partial(_call_llm,token=os.environ["LLM_TOKEN"])
```


## Debug
Pour connaitre précisément les paramètres utilisés pour lancer une os-sandbox, et tester le comportement,
utilisez `python -m pysandboxes.remote.bash -v --os-sandbox=firejail`