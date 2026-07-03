# LangGraph Demo

A demonstration chatbot built with LangGraph featuring two tools:
- **Calculator**: Evaluates mathematical expressions using Python's `eval()`
- **Web Fetcher**: Fetches web pages and converts them to markdown

## Features

- Interactive console chat interface
- Command-line interface (CLI) for quick queries
- Standalone tool commands for calculator and web fetcher
- Full test coverage with pytest
- Type hints and mypy support

## Installation

```bash
# Install dependencies
make install

# Or manually with uv
uv pip install -e ".[dev]"
```

## Configuration

Create a `.env` file in the project root with your OpenAI API key:

```
OPENAI_API_KEY=your-api-key-here
```

## Usage

### Interactive Chat

Start an interactive chat session:

```bash
make chat
# or
langgraph-chat chat
```

### CLI Commands

Ask a single question:

```bash
langgraph-chat ask "What is the square root of 144?"
```

Calculate an expression:

```bash
langgraph-chat calc "2**10"
```

Fetch a web page:

```bash
langgraph-chat fetch "https://example.com"
```

### CLI Options

```bash
langgraph-chat chat --model gpt-4o --temperature 0.7
langgraph-chat ask --model gpt-4o "Your question here"
```

## Development

### Run Tests

```bash
make test
```

### Linting

```bash
make lint
```

### Format Code

```bash
make format
```

### Clean Build Artifacts

```bash
make clean
```

## Project Structure

```
langgraph-demo/
├── langgraph_demo/
│   ├── __init__.py       # Package initialization
│   ├── tools.py          # Calculator and web fetcher tools
│   ├── agent.py          # LangGraph agent implementation
│   ├── console.py        # Interactive console chat
│   └── cli.py            # Command-line interface
├── tests/
│   ├── __init__.py
│   ├── test_tools.py     # Tests for tools
│   ├── test_agent.py     # Tests for agent
│   └── test_cli.py       # Tests for CLI
├── pyproject.toml        # Project configuration
├── Makefile              # Build and development tasks
└── README.md             # This file
```

## Tools Description

### Calculator Tool

The calculator tool evaluates mathematical expressions safely:

- Supports basic arithmetic: `+`, `-`, `*`, `/`, `**`, `%`
- Math module functions: `sqrt()`, `sin()`, `cos()`, `log()`, etc.
- Built-in functions: `abs()`, `round()`, `min()`, `max()`, `sum()`
- Sandboxed execution with restricted builtins

Example:
```python
calculator("sqrt(144) + 2**3")  # Returns: "20.0"
```

### Web Fetcher Tool

The web fetcher tool retrieves web pages and converts them to markdown:

- Follows redirects automatically
- Converts HTML to clean markdown
- Removes scripts and styles
- Custom user agent for compatibility

Example:
```python
await web_fetcher("https://example.com")  # Returns markdown content
```

## Examples

### Chat Session Example

```
You: What is 2 to the power of 16?
Assistant: The result is 65536.

You: Fetch the content from https://www.python.org
Assistant: I've fetched the Python website. Here's the content in markdown...

You: quit
Goodbye!
```

### CLI Examples

```bash
# Quick calculation
langgraph-chat calc "15 * 23 + 100"

# Ask the agent
langgraph-chat ask "What is the factorial of 5?"

# Fetch and convert a webpage
langgraph-chat fetch "https://docs.python.org"
```

## License

Apache V2

## Author

Philippe Prados (pprados)
