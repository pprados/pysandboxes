# MCP Server

This code is an example implementation of an MCP server.

## Features

It offers the following services:
- [X] Python code execution
- [X] Publishing resources from a directory
- [X] Browsing a WEB page

This demonstrates the added value of **Py-sandboxes**. Security rules will limit the capabilities of the MCP server, using only a parameter file.

## Installation

```bash
cd path/to/mcp-server
uv sync --reinstall
```

## Usage

Like any MCP server, this one can be used either as a subprocess of the MCP Client (`stdio` communication) or as a server listening on a TCP port.

### Complete Mode with stdio
In this scenario, the entire MCP server is under the control of **Py-sandboxes**. The `@sandbox` annotation is ignored.
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

    %% 🎨 Custom style for OSSandbox
    style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
    style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
```
To launch this MCP server, add this line to your client's parameters, from the server's directory.
```bash
# Add this command line in the parameter of the MCP client
uv run -m mcp_server.main -t stdio
```
For example, for [claude-code](https://claude.com/product/claude-code), invoke:
```bash
claude mcp remove mcp_demo
claude mcp add mcp_demo -- uv run -m mcp_server.main -t stdio
```
or use the [MCP client](../mcp-client/README.md).

### Partial Mode with stdio
In this scenario, part of the MCP server is under the control of **py-sandboxes**. The client invokes the MCP server, part of which runs in a sandbox (`@sandbox` annotation). 
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

    %% 🎨 Custom style for OSSandbox
    style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
    style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
```

To launch this MCP server, add this line to your client's parameters, from the server's directory.
```bash
# Add this command line in the parameter of the MCP client
uv run -m mcp_server.main -t stdio
```

For example, for [claude-code](https://claude.com/product/claude-code), invoke:
```bash
claude mcp remove mcp_demo
claude mcp add mcp_demo -- uv run -m mcp_server.main -t stdio
```
or use the [MCP client](../mcp-client/README.md).

### Complete mode with http
In this scenario, the server must be started before the client. It exposes an HTTP endpoint to allow the client to connect to it.

```mermaid
flowchart TD
    subgraph Docker1 ["Node/VM/Container"]
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end
    end
    subgraph Docker2 ["Node/VM/Container"]
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

    %% 🎨 Custom style for OSSandbox
    style Docker1 fill:#C195DB
    style Docker2 fill:#C195DB
    style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
    style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
```
TODO: to be checked with claude
```bash
cd path/to/mcp-server
uv run -m mcp_server.main -t http --port 8000
```
or use the [MCP client](../mcp-client/README.md).

### Partial mode with http
In this scenario, the server must be started before the client. It exposes an HTTP endpoint to allow the client to connect to it. It is itself divided into two parts (`@sandbox` annotation).

```mermaid
flowchart TD
    subgraph Docker1 ["Node/VM/Container"]
        subgraph MCPClient ["MCP Client"]
            D[Chat]
        end
    end
    subgraph Docker2 ["Node/VM/Container"]
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

    %% 🎨 Custom style for OSSandbox
    style Docker1 fill:#C195DB
    style Docker2 fill:#C195DB
    style OSSandbox fill:#ebe0d0,stroke:#2f2617,stroke-width:4px
    style PythonSandbox fill:#aa7c52,stroke:#2f2617,stroke-width:4px
```
TODO: to be checked with claude
```bash
cd path/to/mcp-server
uv run -m mcp_server.main -t streamable-http --port 3001
```
or use the [MCP client](../mcp-client/README.md).

## Client
For the client, consult the specific documentation. For example, [here](../mcp-client/README.md)
