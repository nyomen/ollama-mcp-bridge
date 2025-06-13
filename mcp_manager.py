"""MCP Server Management"""
import json
from contextlib import AsyncExitStack
from typing import Dict, List
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from loguru import logger
import ollama
from ollama import ChatResponse


class MCPManager:
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.sessions: Dict[str, ClientSession] = {}
        self.all_tools: List[dict] = []
        self.exit_stack = AsyncExitStack()
        self.ollama_client = ollama.AsyncClient(host=ollama_url)

    async def load_servers(self, config_path: str):
        """Load and connect to all MCP servers from config"""
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)

        for name, server_config in config['mcpServers'].items():
            try:
                await self._connect_server(name, server_config)
            except Exception as e:
                logger.error(f"Failed to connect to {name}: {e}")

    async def _connect_server(self, name: str, config: dict):
        """Connect to a single MCP server"""
        params = StdioServerParameters(
            command=config['command'],
            args=config['args'],
            env=config.get('env')
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(params))
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()

        self.sessions[name] = session

        # Get tools from this server
        meta = await session.list_tools()
        for tool in meta.tools:
            tool_def = {
                "type": "function",
                "function": {
                    "name": f"{name}_{tool.name}",
                    "description": tool.description,
                    "parameters": tool.inputSchema
                },
                "server": name,
                "original_name": tool.name
            }
            self.all_tools.append(tool_def)

        logger.info(f"Connected to '{name}' with {len(meta.tools)} tools")

    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool on the appropriate server"""
        # Find the tool and extract server name
        tool_info = None
        for tool in self.all_tools:
            if tool["function"]["name"] == tool_name:
                tool_info = tool
                break

        if not tool_info:
            raise ValueError(f"Tool {tool_name} not found")

        server_name = tool_info["server"]
        original_name = tool_info["original_name"]
        session = self.sessions[server_name]

        result = await session.call_tool(original_name, arguments)
        return result.content[0].text

    async def query_with_tools(self, query: str, model: str = "qwen3:0.6b") -> str:
        """Send query to Ollama with tool processing"""
        messages = [{"role": "user", "content": query}]

        # Initial call with all available tools
        resp: ChatResponse = await self.ollama_client.chat(
            model=model,
            messages=messages,
            think=False,
            stream=False,
            tools=self.all_tools
        )

        final_response = ""

        # Handle tool calls
        if resp.message.tool_calls:
            for tool_call in resp.message.tool_calls:
                # Call the MCP tool
                tool_result = await self.call_tool(
                    tool_call.function.name,
                    tool_call.function.arguments
                )

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": tool_result
                })

            # Get final response from model with tool results
            final_resp = await self.ollama_client.chat(
                model=model,
                messages=messages,
                think=False,
                stream=False,
            )
            final_response = final_resp.message.content
        else:
            # If no tool calls, just return the initial response
            final_response = resp.message.content

        return final_response

    async def cleanup(self):
        """Clean up all connections"""
        await self.exit_stack.aclose()
