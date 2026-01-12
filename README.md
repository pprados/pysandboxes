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