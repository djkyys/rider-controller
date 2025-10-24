import asyncio
import node_client
from typing import Dict

async def all_nodes_idle(nodes: Dict[str, str]) -> bool:
    """Check if all nodes are idle (not recording, not converting)"""
    status_results = await node_client.status_all_nodes(nodes)
    
    for result in status_results:
        if not result['success']:
            return False
        
        data = result['data']
        state = data.get('state', 'unknown')
        recording = data.get('recording', False)
        
        # Not idle if recording or converting
        if recording or state in ['recording', 'converting']:
            return False
    
    return True


async def wait_and_poweroff(nodes: Dict[str, str], max_wait_seconds: int = 300):
    """
    Poll nodes until all are idle, then poweroff this Pi.
    """
    # Poll every 5 seconds
    for _ in range(max_wait_seconds // 5):
        if await all_nodes_idle(nodes):
            # All idle, poweroff this Pi
            process = await asyncio.create_subprocess_exec(
                'sudo', 'poweroff',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            return {"success": True, "message": "Powering off"}
        
        await asyncio.sleep(5)
    
    # Timeout
    return {"success": False, "error": "Timeout waiting for nodes to be idle"}
