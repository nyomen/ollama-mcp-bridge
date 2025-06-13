"""FastAPI application"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger
from mcp_manager import MCPManager


# Simple models
class QueryRequest(BaseModel):
    query: str
    model: Optional[str] = "qwen3:0.6b"


# Global manager - will be initialized in lifespan
mcp_manager: Optional[MCPManager] = None


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """FastAPI lifespan events"""
    global mcp_manager

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


@app.post("/query")
async def query(request: QueryRequest):
    """Send a query to Ollama with all available MCP tools"""
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP manager not initialized")

    try:
        logger.debug(f"Processing query: {request.query}")
        response = await mcp_manager.query_with_tools(request.query, request.model)
        return {"response": response}
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}") from e
