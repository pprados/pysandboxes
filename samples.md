# Samples
Nous proposons plusieurs scénarios d'utilisation de *Py-Sandboxes*.

## MCP
Une utilisation classique et un des objectifs initial du projet, est de l'utiliser dans le cadre d'un renforcement de sécurité lors de l'utilisations d'outils avec un modèle de langage (LLM).

La spécification [MCP](https://modelcontextprotocol.io/specification/2025-06-18) propose des API pour Python, pour exposer des outils via ce protocole, et pour créer un client MCP pour invoquer ces outils.

### Scénario API MCP
Dans ce scénario, nous allons exposer un serveur MCP pour qu'il soit utilisé par des applications d'IA générative comme "Claude Desktop" ou autres.

Le code du serveur peut être intégralement isolé dans plusieurs bac-à-sables (complete mode). Pour cela, il y a plusieurs approches:
1. Laisser l'utilisateur paramétrer l'intégration du serveur MCP pour utiliser ou non *python-sb* avec un jeu de paramètre qui lui est propre
2. Intégrer le paramétrage de **Py-sandboxes** avec le module MCP. Ainsi, s'il est lancé par `python-sb` les paramètres proposées seront utilisé
3. Proposer un lancement uniquement avec **Py-sandboxes**. Dans ce cas, les paramètres doivent accompagner le module. C'est propablement la meilleur approche pour publier un module MCP sécurisé. L'utilisateur peut éventuellement valoriser la variable d'environnement `OS_SANDBOX` pour choisir l'implémentation qu'il lui convient.

#### 1. Scénario à la main de l'utilisateur
Dans ce scénario, l'utilisateur choisi d'ajouter `python-sb --pysandboxes-config=...` pour le lancement du serveur MCP. Il peut ainsi indiquer uniquement les autorisations souhaités.


#### 2. Scénario pré-paramétré

#### 3. Scénario pré-paramétré


### Scénarion MCP client
Dans ce scénario, c'est le client MCP qui est isolé dans un bac-à-sable. Ce qui est interressant dans ce dernier, est que le client MCP étant dans un 'OS-sandbox', tous les serveurs MCP qu'il utilise, via le protocole `stdio`, bénéficie de la même isolation. En effet, le client MCP lance des processus fils avec les serveurs MCP stdio qu'il utilise.
Il peut être nécessaire d'enrichir les règles de `.py-sandboxes` pour ajouter éventuellement des privilèges que les serveurs MCP ont besoins (accès réseaux, disque, etc). Lors du lancement de l'OS-sandbox, ces paramètres permettrons d'étendre les authorisations.