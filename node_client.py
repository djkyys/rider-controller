import aiohttp
import asyncio

async def get_node_stats(node_url: str):
    """Query a node for its system stats"""
    timeout = aiohttp.ClientTimeout(total=5)  # 5 second timeout
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{node_url}/system") as response:
            if response.status == 200:
                return await response.json()
            else:
                return {"error": f"Node returned status {response.status}"}
