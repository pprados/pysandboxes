# MCP Simple Chatbot

This example demonstrates how to integrate the Model Context Protocol (MCP) into a simple CLI chatbot. Il est paramétré pour utiliser les outils de [`../mcp-server`](../mcp-server/README.md) via **Py-sandboxes**.

## Installation
1. **Install the dependencies:**
    Use uv
    ```bash
    cd path/to/mcp-client
    uv sync
    ```
2. **Set up environment variables:**

    Create a `.env` file in the root directory and add your API key:
    
    ```plaintext
    GROK_API_KEY=your_api_key_here
    ```
    
    > **Note:** The current implementation is configured to use the Groq API endpoint (`https://api.groq.com/openai/v1/chat/completions`) with the `llama-3.2-90b-vision-preview` model. If you plan to use a different LLM provider, you'll need to modify the `LLMClient` class in `main.py` to use the appropriate endpoint URL and model parameters.

3. **Configure servers:**

     The `servers_config.json` follows the same structure as Claude Desktop, allowing for easy integration of multiple servers.
     Here's some examples. You must choice only one:

    1. **Use without sandboxes**

    Cette version permet de lancer le **MCP-server** en mode `stdio`, sans **PY-sandboxes**.
    ```mermaid
    flowchart TD
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end
   
        subgraph MCPServer ["MCP Server"]
    
            A[Caller Code]
            C["<s>@sandbox</s><br/>my_function(...)"]
        end
    
        D -- "stdio" --> A
        A -- "1- my_function(param)" --> C
        C -- "4- return" --> A

    ```

    Executez la commande suivante pour lancer de mode.
    ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_no_sandboxes.json
    ```
    2. **Use python-sb (complete mode)**

    Cette version permet d'isoler le mcp-server en mode `stdio`, avec **PY-sandboxes**.
       
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
    Executez la commande suivante pour lancer de mode.
    ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_complete_mode.json
    ```
   3. **Use python-sb (partial mode)**

   Cette version permet d'isoler le **MCP server** en mode `stdio`, avec **PY-sandboxes**.

    ```mermaid
    flowchart TD
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end

        subgraph MCPServer ["MCP Server"]
            subgraph WithSandboxes ["with sandboxes()"]
                A[Caller Code]
            end
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
   Executez la commande suivante pour lancer ce mode.
   ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_selected_mode.json
   ```

## Usage

1. **Run the client:**

   1.  without sandboxes
       Dans ce scénario, les bac-à-sables sont complètement désactivé.
    ```mermaid
    flowchart TD
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end

        subgraph MCPServer ["MCP Server"]
           A[...]
        end

        D -- "stdio" --> A
    ```
   ```bash
   uv run -m mcp_sample_chatbot.main -c servers_config_no_sandboxes.json
   ```
   2.  inside a sandboxes
   
       Dans ce scénario, l'intégralité de l'architecture MCP est dans une OS-sandbox. L'invocation des serveurs s'effectuant via le protocole stdio, et des sous-processus, ces derniers s'executent dans la même OS-sandbox. Vous devez alors la paramétrer, au niveau du client, pour garder les privilèges combinés du MCP client et de ses MCP serveur.
       Le MCP serveur doit être lancé avec un `--os-sandbox=subprocess` qu'il n'y ai pas de nouveau *OS-sandbox* encapsulé. Le MCP serveur peut avoir ses propres paramètres de *Python-sandbox* si besoin.
    ```mermaid
    flowchart TD
        subgraph OSSandbox ["OS-sandbox"]
            direction TB
            subgraph PythonSandbox1 [Python Sandbox]
              subgraph MCPClient ["MCP Client"]
                  D[Chat]
              end
            end   
            subgraph PythonSandbox2 [Python Sandbox]
                subgraph MCPServer ["MCP Server"]
                   A[...]
                end
            end
        end
    
        D -- "stdio" --> A
   
        %% 🎨 Style personnalisé pour OSSandbox
        style OSSandbox fill:#E6DCDA,stroke:#006064,stroke-width:2px
        style PythonSandbox1 fill:#986F67,stroke:#006064,stroke-width:2px
        style PythonSandbox2 fill:#986F67,stroke:#006064,stroke-width:2px
    ```
   
   ```bash
   uv run -m pysandboxes.python_sb -m mcp_sample_chatbot.main
   ```

2. **Interact with the assistant:**

   The assistant will automatically detect available tools and can respond to queries based on the tools provided by the configured servers. Try `calc 2+3`

3. **Exit the session:**

   Type `quit` or `exit` to end the session.
