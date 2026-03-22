# reflex-langgraph-challenge

agentic ai fullstack web app with reflex v0.8.27 + langgraph v1.0.9 + openai v2.23 + google-genai v1.64

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
$ uv add python-dotenv requests streamlit reflex
$ uv add openai litellm google-adk google-genai
$ uv add langchain langgraph langsmith
$ uv add --group dev ipykernel
```

- add api keys environments

```bash
$ cat .env
OPENAI_API_KEY="..."
OPENAI_VECTOR_STORE_ID="..."
GEMINI_API_KEY="..."
```

### run app

- startup streamlit app

```bash
$ uv sync
$ uv run streamlit run main.py
$ curl localhost:8501
```

- startup adk app

```bash
$ uv sync
$ uv run adk web
$ curl localhost:8000
```
