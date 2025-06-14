"""Simple CLI entry point for MCP Proxy"""
import typer
import uvicorn
import httpx
import subprocess
import platform
import time
from loguru import logger
from api import app

# Start Ollama in background

def start_ollama(model: str):
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        startupinfo = None

    subprocess.Popen(
        ["ollama", "run", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        startupinfo=startupinfo
    )

# Wait until Ollama is ready

def wait_for_ollama(url, retries=10):
    for _ in range(retries):
        try:
            resp = httpx.get(url)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("Ollama did not start in time.")

def main(
    config: str = typer.Option("mcp-config.json", "--config", help="Path to MCP config JSON file"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to"),
    model: str = typer.Option("qwen3:0.6b", "--model", help="Model that gets initialized by ollama"),
    port: int = typer.Option(8000, "--port", help="Port to bind to"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url", help="Ollama server URL"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload")
):
    """Start the Ollama server"""
    start_ollama(model)
    wait_for_ollama(ollama_url)

    """Start the MCP proxy server"""
    # Store config in app state so lifespan can access it
    app.state.config_file = config
    app.state.ollama_url = ollama_url
    
    logger.info(f"Starting MCP proxy server on {host}:{port}")
    logger.info(f"Using Ollama server: {ollama_url}")
    logger.info(f"Using config file: {config}")
    
    # Start the server
    uvicorn.run("api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    typer.run(main)
