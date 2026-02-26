# MCP Server

Ce code est une exemple d'implémentation d'un serveur MCP
## Features

Il offrant les services suivants:
- [X] Execution de code python
- [ ] Publication de ressources venant d'un répertoire
- [ ] Navigation sur une page WEB

Cela permet de montrer la valeur ajoutée de **Py-sandboxes**. Des règles de sécurités vont permettre de limiter les capacités du serveur MCP, uniquement à l'aide d'un fichier de paramètres.

## Installation

```bash
cd path/to/mcp-server
uv sync --reinstall
```

## Usage

Comme tous serveur MCP, ce dernier peut être utilisé, soit comme un sous-processus du MCP Client (communication `stdio`), soit comme un serveur en écoute sur un port TCP.

### Complete Mode with stdio
Dans ce scénario, l'intégralité du serveur MCP est sous le controle de **Py-sandboxes**. L'annotation `@sandbox` est ignorée.
```mermaid
flowchart TD
    subgraph MCPClient ["MCP Client"]
        D[Chat]
    end
    subgraph OSSandbox ["OS-sandbox"]
        direction LR
        subgraph PythonSandbox [Python Sandbox]

            subgraph MCPServer [MCP Server]
                A[Caller Code]
                C["<s>@sandbox</s><br/>my_function(...)"]
            end
        end
    end

    D -- "stdio" --> A
    A -- "1- my_function(param)" --> C
    C -- "4- return" --> A

    %% 🎨 Style personnalisé pour OSSandbox
    style OSSandbox fill:#E6DCDA,stroke:#006064,stroke-width:2px
    style PythonSandbox fill:#986F67,stroke:#006064,stroke-width:2px
```
Pour lancer ce MCP serveur, ajoutez cette ligne dans les paramètres de votre client, depuis le répertoire du serveur.
```bash
# Add this command line in the paramater of the MCP client
uv run -m mcp_server.main -t stdio
```
### Partial Mode with stdio
Dans ce scénario, une partie du serveur MCP est sous le controle de **py-sandboxes**. Le client invoque le serveur MCP, dont une partie s'exécute dans un bac-à-sable (annotation `@sandbox`). 
```mermaid
flowchart TD
    subgraph MCPClient ["MCP Client"]
        D[Chat]
    end
    subgraph MCPServer ["MCP Server"]
        A[Caller Code]
    end
    subgraph OSSandbox ["OS-sandbox"]
        direction TB
        subgraph PythonSandbox [Python Sandbox]
             C["<b>@sandbox</b><br/>my_function(...)"]
        end
    end

    D -- "stdio" --> A
    A -- "1- my_function(param)" --> C
    C -- "4- return" --> A

    %% 🎨 Style personnalisé pour OSSandbox
    style OSSandbox fill:#E6DCDA,stroke:#006064,stroke-width:2px
    style PythonSandbox fill:#986F67,stroke:#006064,stroke-width:2px
```

### Complete mode with streamable-http
Dans ce scénario, le serveur doit être lancé avant le client. Il expose un end-point HTTP, pour permettre au client de s'y connecter.

```mermaid
flowchart TD
    subgraph Docker1 ["VM/Container Client"]
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end
    end
    subgraph Docker2 ["VM/Container Server"]
        subgraph OSSandbox ["OS-sandbox"]
            direction LR
            subgraph PythonSandbox [Python Sandbox]

                subgraph MCPServer [MCP Server]
                    A[Caller Code]
                    C["<s>@sandbox</s><br/>my_function(...)"]
                end
           end
        end
    end

    D -- "http POST & GET" --> A
    A -- "1- my_function(param)" --> C
    C -- "4- return" --> A

    %% 🎨 Style personnalisé pour OSSandbox
    style Docker1 fill:#C195DB,stroke:#006064,stroke-width:2px
    style Docker2 fill:#C195DB,stroke:#006064,stroke-width:2px
    style OSSandbox fill:#E6DCDA,stroke:#006064,stroke-width:2px
    style PythonSandbox fill:#986F67,stroke:#006064,stroke-width:2px
```

```bash
cd path/to/mcp-server
uv run -m mcp_server.main -t streamable-http --port 3001
```

### Partial mode with streamable-http
Dans ce scénario, le serveur doit être lancé avant le client. Il expose un end-point HTTP, pour permettre au client de s'y connecter. Lui même est découpé en deux partie (annotation `@sandbox`).

```mermaid
flowchart TD
    subgraph Docker1 ["VM/Container Client"]
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end
    end
    subgraph Docker2 ["VM/Container Server"]
        subgraph MCPServer [MCP Server]
            subgraph WithSandboxes ["with sandboxes()"]
                A[Caller Code]
            end
        end

        subgraph OSSandbox ["OS-sandbox"]
            direction LR
            subgraph PythonSandbox [Python Sandbox]
               C["<b>@sandbox</b><br/>my_function(...)"]
           end
        end
    end

    D -- "http POST & GET" --> A
    A -- "1- my_function(param)" --> C
    C -- "4- return" --> A

    %% 🎨 Style personnalisé pour OSSandbox
    style Docker1 fill:#C195DB,stroke:#006064,stroke-width:2px
    style Docker2 fill:#C195DB,stroke:#006064,stroke-width:2px
    style OSSandbox fill:#E6DCDA,stroke:#006064,stroke-width:2px
    style PythonSandbox fill:#986F67,stroke:#006064,stroke-width:2px
```

```bash
cd path/to/mcp-server
uv run -m mcp_server.main -t streamable-http --port 3001
```

## Client
Pour le client, consultez la documentation spécifique. Par exemple, [ici](../mcp-client/README.md)
