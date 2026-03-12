# Samples
We offer several scenarios for using **Py-Sandboxes**, combined with different frameworks.

## MCP
One of the initial goals of the project is to enhance security when using tools with a language model (LLM).

The [MCP](https://modelcontextprotocol.io/specification/2025-06-18) specification provides Python APIs to expose tools via this protocol, and to create or connect MCP clients to invoke these tools ([MCP Client](https://modelcontextprotocol.io/clients)).

### Standard Python MCP API
In this scenario, we will expose an MCP server to be used by generative AI applications.

Depending on the launch command, the MCP server will be more or less isolated from the OS or the client.

#### MCP Client
The [MCP client](../samples/mcp-client/README.md) sub-project offers different launch scenarios to add sandboxes in an architecture combining an MCP client and an MCP server.

#### MCP Server
The [MCP server](../samples/mcp-server/README.md) sub-project offers different launch scenarios to isolate the MCP server to a greater or lesser extent.
