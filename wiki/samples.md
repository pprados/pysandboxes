# Samples
Nous proposons plusieurs scénarios d'utilisation de **Py-Sandboxes**, combiné à différents frameworks.

## MCP
Un des objectifs initial du projet, est de renforcer la sécurité lors de l'utilisations d'outils avec un modèle de langage (LLM).

La spécification [MCP](https://modelcontextprotocol.io/specification/2025-06-18) propose des API pour Python, pour exposer des outils via ce protocole, et pour créer ou connecter des clients MCP pour invoquer ces outils ([Client MCP](https://modelcontextprotocol.io/clients)) .

### Standard python API MCP
Dans ce scénario, nous allons exposer un serveur MCP pour qu'il soit utilisé par des applications d'IA générative.

Suivant la commande de lancement, le serveur MCP sera plus ou moins isolés de l'OS ou du client.

#### MCP Client
Le sous-project [MCP client](../samples/mcp-client/README.md) propose différent scénarios de lancement, pour ajouter des bac-à-sables dans une architecture combinant un MCP client et un MCP server.

#### MCP Server
Le sous-project [MCP server](../samples/mcp-server/README.md) propose différent scénario de lancement pour isoler plus ou moins le serveur MCP.
