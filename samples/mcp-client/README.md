# MCP Simple Chatbot

This example demonstrates how to integrate the Model Context Protocol (MCP) into a simple CLI chatbot. It is configured to use the tools from [`../mcp-server`](../mcp-server/README.md) via **Py-sandboxes**.

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
    
    > **Note:** The current implementation is configured to use the Groq API endpoint (`https://api.groq.com/openai/v1/chat/completions`) with the `llama-3.2-90b-vision-preview` model. If you plan to use a different LLM provider, you\'ll need to modify the `LLMClient` class in `main.py` to use the appropriate endpoint URL and model parameters.

3. **Configure servers:**

     The `servers_config.json` follows the same structure as Claude Desktop, allowing for easy integration of multiple servers.
     MCP\'s `stdio` mode consists of launching a child process with the MCP server. The client can then configure the launch to use different sandboxing scenarios.
     Here\'s some examples. You must choice only one:

    1. **MCP Client use `stdio` to call MCP Server without sandboxes**

    This version allows launching the **MCP-server** in `stdio` mode, without **PY-sandboxes**.
    ```mermaid
    flowchart TD
        subgraph MCPClient [\"MCP Client\"]
            D[Chat]
        end
   
        subgraph MCPServer [\"MCP Server\"]
    
            A[Caller Code]
            C[\"<s>@sandbox</s><br/>my_function(...)\"]
        end
    
        D -- \"stdio\" --> A
        A -- \"1- my_function(param)\" --> C
        C -- \"4- return\" --> A

    ```

    Execute the following command to launch this scenario.
    ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_no_sandbox.json
    ```
    2. **MCP Client use `stdio` to call MCP Server with `python-sb` in complete mode**

    This version allows isolating the mcp-server in `stdio` mode, with **PY-sandboxes**.
       
    ```mermaid
    flowchart TD
        subgraph MCPClient [\"MCP Client\"]
            D[Chat]
        end

        subgraph OSSandbox [\"OS-sandbox\"]
            direction LR
            subgraph PythonSandbox [Python Sandbox]
    
                subgraph MCPServer [MCP Server]
                    A[Caller Code]
                    C[\"<s>@sandbox</s><br/>my_function(...)\"]
                end
            end
        end
    
        D -- \"stdio\" --> A
        A -- \"1- my_function(param)\" --> C
        C -- \"4- return\" --> A

        %% 🎨 Style personnalisé pour OSSandbox
        style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
        style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
    ```
    Execute the following command to launch this mode.
    ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_complete_mode.json
    ```
   3. **MCP Client use `stdio` to call MCP Server with `python-sb` with partial mode**

   This version allows isolating a part of the **MCP server** in `stdio` mode, with **PY-sandboxes**.

    ```mermaid
    flowchart TD
        subgraph MCPClient [\"MCP Client\"]
            D[Chat]
        end

        subgraph MCPServer [\"MCP Server\"]
            subgraph WithSandboxes [\"with sandboxes()\"]
                A[Caller Code]
            end
        end

        subgraph OSSandbox [\"OS-sandbox\"]
            direction TB
            subgraph PythonSandbox [Python Sandbox]
                 C[\"<b>@sandbox</b><br/>my_function(...)\"]
            end
        end
    
        D -- \"stdio\" --> A
        A -- \"1- my_function(param)\" --> C
        C -- \"4- return\" --> A

        %% 🎨 Style personnalisé pour OSSandbox
        style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
        style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px

    ```
   Execute the following command to launch this mode.
   ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_selected_mode.json
   ```
## Usage

1. **Run the client:**

   The client itself may or may not be in a sandbox. The configuration must allow it to invoke the server and the LLM API.
   1.  without sandboxes
       In this scenario, sandboxes are completely disabled.
    ```mermaid
    flowchart TD
        subgraph MCPClient [\"MCP Client\"]
            D[Chat]
        end

        subgraph MCPServer [\"MCP Server\"]
           A[...]\
        end

        D -- \"stdio\" --> A
    ```
   ```bash
   uvx  mcp-simple-chatbot -c servers_config_no_sandboxes.json
   ```
   2.  inside a sandboxes
   
       In this scenario, the entire MCP architecture is in an OS-sandbox. Since server invocation is done via the `stdio` protocol and subprocesses, they run in the same **OS-sandbox**. You must then configure it at the client level to keep the combined privileges of the MCP client and its MCP server.
       The MCP server must be launched with `--os-sandbox=subprocess` so that there is no new encapsulated **OS-sandbox**. The MCP server can have its own **Python-sandbox** parameters if needed.
    ```mermaid
    flowchart TD
        subgraph OSSandbox [\"OS-sandbox\"]
            direction TB
            subgraph PythonSandbox1 [Python Sandbox]
              subgraph MCPClient [\"MCP Client\"]
                  D[Chat]
              end
            end   
            subgraph PythonSandbox2 [Python Sandbox]
                subgraph MCPServer [\"MCP Server\"]
                   A[...]\
                end
            end
        end
    
        D -- \"stdio\" --> A
   
        %% 🎨 Style personnalisé pour OSSandbox
        style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
        style PythonSandbox1 fill:#aa7c52,stroke:#2f2617,stroke-width:4px
        style PythonSandbox2 fill:#aa7c52,stroke:#2f2617,stroke-width:4px
    ```
   
   ```bash
   uv run -m pysandboxes.python_sb -m mcp_sample_chatbot.main
   ```
   
   3. **Isolated MCP client use MCP Server with `http` protocol**

   This version allows isolating the client with **PY-sandboxes** and invoking the MCP via the `http` protocol. The latter is isolated according to the launch parameters (see [here](../mcp-server/README.md))

    ```mermaid
    flowchart TD
        subgraph OSSandbox [\"OS-sandbox\"]
            direction LR
            subgraph PythonSandbox [Python Sandbox]
                subgraph MCPClient [MCP Client]
                    D[Chat]
                end
            end
        end
    
        subgraph MCPServer [\"MCP Server\"]
            A[Caller Code]
            C[\"@sandbox<br/>my_function(...)\"]
        end

        D -- \"http\" --> A
        A -- \"1- my_function(param)\" --> C
        C -- \"4- return\" --> A

        %% 🎨 Style personnalisé pour OSSandbox
        style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
        style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
    ```
   Execute the following command to launch this mode.
   ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_http.json
   ```


2. **Interact with the assistant:**

   The assistant will automatically detect available tools and can respond to queries based on the tools provided by the configured servers. Try `calc 2+3`

3. **Exit the session:**

   Type `quit` or `exit` to end the session.
