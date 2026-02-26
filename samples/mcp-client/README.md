# MCP Simple Chatbot

This example demonstrates how to integrate the Model Context Protocol (MCP) into a simple CLI chatbot. Il est paramétré pour utiliser les outils de `../mcp-server` via **Py-sandboxes**.

Consultez le fichier `servers_config.json` pour selectionner les différentes variations de lancement du MCP server.

## Installation
1. **Install the dependencies:**
    Use uv
    ```bash
    cd samples/mcp-client
    uv sync --reinstall
    ```
2. **Set up environment variables:**

    Create a `.env` file in the root directory and add your API key:
    
    ```plaintext
    GROK_API_KEY=your_api_key_here
    ```
    
    **Note:** The current implementation is configured to use the Groq API endpoint (`https://api.groq.com/openai/v1/chat/completions`) with the `llama-3.2-90b-vision-preview` model. If you plan to use a different LLM provider, you'll need to modify the `LLMClient` class in `main.py` to use the appropriate endpoint URL and model parameters.

3. **Configure servers:**

     The `servers_config.json` follows the same structure as Claude Desktop, allowing for easy integration of multiple servers.
     Here's some examples. You must choice only one:

    1. **Use python-sb (complete mode)**

    Cette version permet d'isoler le mcp-server en mode stdio, dans **PY-sandboxes**. The confugration is in `../mcp-server/mcp_server/.py-sandboxes`
       
    Executez la commande suivante, pour valoriser `servers_config.json`.
    ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_complete_mode.json
    ```
   2. **Use python-sb (partial mode)**

      Cette version permet d'isoler le mcp-server en mode stdio, dans **PY-sandboxes**.
   Executez la commande suivante, pour valoriser `servers_config.json`.
   ```bash
   uv run -m mcp_simple_chatbot.main -c servers_config_selected_mode.json
   ```

## Usage

1. **Run the client:**

   ```bash
   uv run -m mcp_sample_chatbot.main
   ```

2. **Interact with the assistant:**

   The assistant will automatically detect available tools and can respond to queries based on the tools provided by the configured servers. Try `calc 2+3`

3. **Exit the session:**

   Type `quit` or `exit` to end the session.
