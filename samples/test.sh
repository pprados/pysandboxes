#!/bin/bash
cd langchain-demo
make init
CHAT_MODEL="${CHAT_MODEL:-groq:llama-3.3-70b-versatile}" uv run python -m langchain_demo.main
cd ..
