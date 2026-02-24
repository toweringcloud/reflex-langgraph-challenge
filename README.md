# reflex-langgraph-challenge

agentic ai fullstack web app with python v3.12 + reflex v0.8.27 + langgraph v1.0.9 + openai v2.23 + google-genai v1.64

## how to run

### setup

- install python

```bash
$ python --version
Python 3.12.8
```

- install uv

```bash
$ curl -LsSf https://astral.sh/uv/install.sh | sh
$ uv --version
uv 0.8.21 (f64da2745 2025-09-23)
```

### configure

- install packages

```bash
$ uv init
$ uv add reflex langchain langgraph openai google-genai
$ uv add --group dev ipykernel
```

### run

- startup reflex service

```bash
$ uv run reflex
```
