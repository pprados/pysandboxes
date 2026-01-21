La programmation moderne, fait souvent appel à la génération de code ou à l'invocation d'API par des modèles de langagues (LLM).
Ces derniers peuvent être manipulé pour exécuter des commandes malveillantes.
L'[OWASP](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/) présente une liste des risques associés à l'utilisation de ces modèles.
Key security risks (based on the OWASP Top 10 for LLM Applications):
- LM01: Prompt Injection — Malicious prompts can bypass filters and trigger unintended actions.
- LLM02: Insecure Output Handling — Raw, sensitive data (e.g., credentials) can be leaked.
- LLM04: Model DoS — Heavy prompts can overwhelm and crash systems.
- LLM05: Supply Chain Vulnerabilities — Malicious packages can be introduced via unverified MCP servers/tools.
- LLM06: Information Disclosure — Revealing server details can aid attackers.
- LLM09: Overreliance on AI — Unreviewed automation can lead to dangerous outcomes.


Par exemple, un serveur MCP qui expose un service permettant de consulter une page WEB peut être abusé, pour lui demander de consulter une page sur localhost, une adresse sur l'intranet ou sur file:/// pour lire des fichiers locaux.
Un code généré par un LLM peut générer une invocation d'expression régulière spécialement formé pour entrainter un dénis de service (Voir catastrophic backpropagation)

Parmis ces risques, certains peuvent être réduire si une partie du code applicatif est exécutant dans un bac à sable dédié.
L'idée est d'utiliser une approche de sécurité en profondeur, où plusieurs couches s'épaule les unes des autres, pour limiter au maximum les capacités et les privilèges nécessaires à chaque composant. Est-ce judicieux de permettre à chaque code python ou dépendance d'avoir accès à tous les fichiers de l'applications ou de pouvoir dépendre de nouveau module inconnu ?

La solution `pysandboxes` que nous proposons vise à répondre à ces questions. L'idée est de proposer un mécanisme de "Sandbox python", permettant l'exécution d'un code python, mais limité dans ces capacités. C'est une approche similaire à [AppArmor](https://apparmor.net/) ou `firejail`.
L'approche consiste à filtrer et renforcer les API standards Python, pour limiter les capacités d'actions de l'application. Cette approche, par détournement d'API est efficace, mais ne peut pas garantir qu'il n'y a pas de solution de contournement. C'est pour cela que notre solution permet l'emboitement d'autres technologies, de type os-sandbox. Ces technologies s'appuis sur les capacités de l'OS à limiter les accès réseaux, disques, ressources, etc. Emboiter un os-sandbox avec un py-sandbox est une combinaison interressante pour controler la sécurité des applications.

Notre solution permet de réduire les risques suivant:
- **Path Traversal**: Seul les répertoires autorisés peuvent être accédés.
- **Remote Code Execution (RCE)**: Les apis sensibles ne sont pas disponibles
- **Reverse Shells**: les connexions réseaux sont limités
- **Deni de service**: un timeout peut être ajouté, allant jusqu'a tuer le processus s'il n'est pas possible de l'arréter autrement
- **Execution malicieuse**: L'invocation d'api sensible comme `eval()` ou `exec()` définissent précisément les syntaxes python valide et une liste blanche de modules python.

Elle limite les possibilités d'attaques suivantes:
- Prompt Injection ou Indirect Prompt Injection: le prompt modifié ne peut pas invoquer n'importe quoi
- Excessive Permissions: tous le code est sous le controle du bac à sable python
- Token Theft: Les fichiers accessibles sont filtrés
- Remote Access: Les actions réseaux et code sont limités


L'approche est basée sur le principe de **Least Privilege** et **Defense in Depth**, avec un paramétrage exclusivement en "liste blanche". Par défaut, tout est interdit. Il faut explicitement autoriser les actions.

Un mécanisme d'apprentissage permet une amélioration continue des règles de sécurité et un démarrage rapide.


TODO: https://xxradar.medium.com/the-security-risks-of-model-context-protocol-mcp-c50c4817e80e


TODO: expliquer qu'il faut créer le fichier .py-sandbox
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
Indiquer également comment se brancher à firejail (`firejail --join=firejail-sandbox`)

- Peux etre utilisé lors de l'apprentisage par renforcement