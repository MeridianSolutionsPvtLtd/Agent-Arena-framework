"""Development launcher with an optional process-local Ollama override."""

import argparse
import os


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Installed Ollama model tag; selects Ollama")
    parser.add_argument("--reload", action="store_true", help="Development auto-reload")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.model is not None:
        model = args.model.strip()
        if not model or any(character.isspace() for character in model):
            parser.error("--model must be a non-empty model tag without whitespace")
        # Apply before importing the FastAPI application so reload workers inherit it.
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = model

    print(
        f"[Startup] LLM_PROVIDER={os.getenv('LLM_PROVIDER', 'ollama')} "
        f"OLLAMA_MODEL={os.getenv('OLLAMA_MODEL', 'llama3.1')} "
        f"OLLAMA_BASE_URL={os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}",
        flush=True,
    )

    import uvicorn

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
