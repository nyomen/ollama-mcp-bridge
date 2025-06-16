"""FastAPI application"""
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from loguru import logger
from mcp_manager import MCPManager


# Global manager - will be initialized in lifespan
mcp_manager: Optional[MCPManager] = None


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """FastAPI lifespan events"""
    global mcp_manager, ollama_url

    # Get config from app state
    config_file = getattr(fastapi_app.state, 'config_file', 'mcp-config.json')
    ollama_url = getattr(fastapi_app.state, 'ollama_url', 'http://localhost:11434')

    # Initialize manager and load servers
    mcp_manager = MCPManager(ollama_url=ollama_url)
    await mcp_manager.load_servers(config_file)
    logger.success(f"Startup complete. Total tools available: {len(mcp_manager.all_tools)}")

    yield

    # Cleanup on shutdown
    if mcp_manager:
        await mcp_manager.cleanup()


# Create FastAPI app
app = FastAPI(
    title="MCP Proxy for Ollama",
    description="Simple API for interacting with MCP servers through Ollama",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "tools": len(mcp_manager.all_tools) if mcp_manager else 0
    }


@app.post("/api/chat")
async def proxy_chat(request: Request):
    """Send a query to Ollama with all available MCP tools"""
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP manager not initialized")

    try:
        data = await request.json()
        messages = data.get("messages", [])
        model = data.get("model")

        # Extract the last user message content
        #content = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        # Extract the full conversation content (user and assistant)
        content = "\n".join(m["content"] for m in messages if "content" in m)

        logger.debug(f"Processing query: {content}")
        response = await mcp_manager.query_with_tools(content, model)
        return response
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}") from e

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_to_ollama(full_path: str, request: Request):
    url = f"{ollama_url}/{full_path}"
    method = request.method
    headers = dict(request.headers)
    body = await request.body()

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=url,
            content=body,
            headers=headers,
            timeout=60.0
        )
    
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("content-type")
    )