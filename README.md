# Synapse

![Dashboard](docs/dashboard.png)

Synapse is a production-grade visual AI pipeline builder. Drag node-shaped processors onto a canvas, wire them up, and ship a working workflow in minutes. A FastAPI backend validates the graph with DAG and missing-input checks, then runs each step in topological order. Built with React Flow, Zustand, Tailwind, and FastAPI.

![Demo](docs/demo.png)
## Features

- **Visual pipeline builder**: Drag various node types — LLMs, vector stores, integrations — onto a canvas and wire them up.
- **Validate + execute**: DAG check (DFS three-color), topo sort (Kahn's), then a mock run that lights up each node in order.
- **Templates + persistence**: Start from curated templates (like RAG, Multi-LLM, Slack bots), save your own, and reload them.
- **Built for power users**: Command palette (⌘K), undo/redo, dark mode, multi-tag, live execution log, and comprehensive backend tests.

## Tech Stack

- **Frontend**: React, React Flow, Zustand, Tailwind CSS
- **Backend**: Python, FastAPI

## Getting Started

*(Add instructions on how to install and run the project locally here)*
