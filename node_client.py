import aiohttp
import asyncio
from typing import Dict, Optional

async def get_node_stats(node_name: str, node_url: str) -> Dict:
    """Query a node for its system stats"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{node_url}/system") as response:
                if response.status == 200:
                    data = await response.json()
                    data['name'] = node_name
                    data['url'] = node_url
                    return data
                else:
                    return {
                        "name": node_name,
                        "url": node_url,
                        "error": f"Node returned status {response.status}"
                    }
    except asyncio.TimeoutError:
        return {
            "name": node_name,
            "url": node_url,
            "error": "Timeout connecting to node"
        }
    except Exception as e:
        return {
            "name": node_name,
            "url": node_url,
            "error": str(e)
        }

# ========== NODE RECORDING API ==========

async def node_ready(node_url: str) -> Dict:
    """Check if node is ready to record"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{node_url}/ready") as response:
            return await response.json()

async def node_status(node_url: str) -> Dict:
    """Get node recording status"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{node_url}/status") as response:
            return await response.json()

async def node_recordings(node_url: str) -> Dict:
    """Get list of recordings from node"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{node_url}/recordings") as response:
            return await response.json()

async def node_start_recording(node_url: str, scheduled: Optional[int] = None, session_id: Optional[str] = None) -> Dict:
    """Start recording on a node with session_id"""
    timeout = aiohttp.ClientTimeout(total=5)
    url = f"{node_url}/start"
    
    # Build URL with parameters
    params = []
    if scheduled:
        params.append(f"scheduled={scheduled}")
    if session_id:
        params.append(f"session_id={session_id}")
    
    if params:
        url += "?" + "&".join(params)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url) as response:
            return await response.json()

async def node_stop_recording(node_url: str) -> Dict:
    """Stop recording on a node"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{node_url}/stop") as response:
            return await response.json()

async def node_cancel_scheduled(node_url: str) -> Dict:
    """Cancel scheduled recording on a node"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.delete(f"{node_url}/scheduled") as response:
            return await response.json()

async def node_delete_recording(node_url: str, session_id: str) -> Dict:
    """Delete a recording from a node"""
    timeout = aiohttp.ClientTimeout(total=5)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.delete(f"{node_url}/recordings/{session_id}") as response:
            return await response.json()

# ========== BULK OPERATIONS ==========

async def start_all_nodes(nodes: Dict[str, str], scheduled: Optional[int] = None, session_id: Optional[str] = None) -> list:
    """Start recording on all nodes simultaneously with session_id"""
    async def start_node(node_name: str, node_url: str):
        try:
            data = await node_start_recording(node_url, scheduled, session_id)
            return {"node": node_name, "success": True, "data": data}
        except Exception as e:
            return {"node": node_name, "success": False, "error": str(e)}
    
    tasks = [start_node(name, url) for name, url in nodes.items()]
    return await asyncio.gather(*tasks)


async def stop_all_nodes(nodes: Dict[str, str]) -> list:
    """Stop recording on all nodes simultaneously"""
    async def stop_node(node_name: str, node_url: str):
        try:
            data = await node_stop_recording(node_url)
            return {"node": node_name, "success": True, "data": data}
        except Exception as e:
            return {"node": node_name, "success": False, "error": str(e)}
    
    tasks = [stop_node(name, url) for name, url in nodes.items()]
    return await asyncio.gather(*tasks)

async def status_all_nodes(nodes: Dict[str, str]) -> list:
    """Get status from all nodes"""
    async def get_status(node_name: str, node_url: str):
        try:
            data = await node_status(node_url)
            return {"node": node_name, "success": True, "data": data}
        except Exception as e:
            return {"node": node_name, "success": False, "error": str(e)}
    
    tasks = [get_status(name, url) for name, url in nodes.items()]
    return await asyncio.gather(*tasks)
