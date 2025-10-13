from fastapi import FastAPI
import json
import asyncio
from typing import Dict

app = FastAPI()

# Load nodes from JSON file
def load_nodes():
    with open('nodes.json', 'r') as f:
        return json.load(f)['nodes']

def save_nodes(nodes):
    with open('nodes.json', 'w') as f:
        json.dump({'nodes': nodes}, f, indent=2)

# Import monitors
from monitors.cpu import get_cpu_stats
from monitors.memory import get_memory_stats
from monitors.disk import get_disk_stats
from monitors.health import get_health_status
import node_client

@app.get("/system")
async def get_system_stats():
    """Get stats from THIS server"""
    # Run all monitors in parallel
    cpu, memory, disk, health = await asyncio.gather(
        get_cpu_stats(),
        get_memory_stats(),
        get_disk_stats(),
        get_health_status()
    )
    
    return {"server": "main", "cpu": cpu, "memory": memory, "disk": disk, "health": health}

@app.get("/nodes")
async def get_all_nodes():
    """Get stats from all nodes in parallel"""
    nodes = load_nodes()
    
    # Query all nodes simultaneously
    tasks = []
    for node_name, node_url in nodes.items():
        tasks.append(node_client.get_node_stats(node_name, node_url))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Format results
    node_results = {}
    for result in results:
        if isinstance(result, dict) and 'name' in result:
            node_results[result['name']] = result
    
    return node_results

@app.post("/nodes/register")
async def register_node(node_name: str, node_url: str):
    """Register a new node"""
    nodes = load_nodes()
    nodes[node_name] = node_url
    save_nodes(nodes)
    return {"message": f"Node {node_name} registered"}
