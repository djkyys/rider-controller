from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import json
import asyncio
from typing import Optional

app = FastAPI()

# ========== CONFIG ==========

def load_nodes():
    with open('nodes.json', 'r') as f:
        return json.load(f)['nodes']

def save_nodes(nodes):
    with open('nodes.json', 'w') as f:
        json.dump({'nodes': nodes}, f, indent=2)

# ========== IMPORTS ==========

from monitors.cpu import get_cpu_stats
from monitors.memory import get_memory_stats
from monitors.disk import get_disk_stats
from monitors.health import get_health_status
from monitors.chrony import get_chrony_stats
import node_client

# ========== THIS SERVER ENDPOINTS ==========

@app.get("/system")
async def get_system_stats():
    """Get stats from THIS server (Pi 4)"""
    cpu, memory, disk, health, chrony = await asyncio.gather(
        get_cpu_stats(),
        get_memory_stats(),
        get_disk_stats(),
        get_health_status(),
        get_chrony_stats()
    )
    
    return {
        "server": "main",
        "cpu": cpu,
        "memory": memory,
        "disk": disk,
        "health": health,
        "time_sync": chrony
    }

@app.get("/time")
async def get_time_sync():
    """Get detailed NTP/Chrony time synchronization info"""
    return await get_chrony_stats()

# ========== NODE MANAGEMENT ==========

@app.get("/nodes")
async def list_nodes():
    """List all registered nodes"""
    nodes = load_nodes()
    return {"nodes": nodes, "count": len(nodes)}

@app.post("/nodes/register")
async def register_node(node_name: str, node_url: str):
    """Register a new node"""
    nodes = load_nodes()
    nodes[node_name] = node_url
    save_nodes(nodes)
    return {"message": f"Node {node_name} registered", "url": node_url}

# ========== SYNCHRONIZED RECORDING API ==========

@app.post("/recording/start/synchronized")
async def start_synchronized_recording(delay: int = 5):
    """
    Start synchronized recording across all camera nodes.
    
    Flow:
    1. Performs thorough pre-flight checks on all nodes
    2. If any node not ready, returns detailed error
    3. If all ready, calculates start_time and schedules all nodes
    4. Returns start_time to phone for synchronized sensor recording
    
    Args:
        delay: Seconds in future to start (default: 5, min: 2, max: 30)
    """
    import time
    
    # Validate delay
    if delay < 2:
        raise HTTPException(status_code=400, detail="Minimum delay is 2 seconds")
    if delay > 30:
        raise HTTPException(status_code=400, detail="Maximum delay is 30 seconds")
    
    nodes = load_nodes()
    
    # ========== THOROUGH PRE-FLIGHT CHECKS ==========
    
    # Check all nodes in parallel
    status_results = await node_client.status_all_nodes(nodes)
    
    node_status = {}
    not_ready = []
    
    for result in status_results:
        node_name = result['node']
        if not result['success']:
            not_ready.append({
                "name": node_name,
                "ready": False,
                "reason": result.get('error', 'Unable to connect')
            })
            node_status[node_name] = {"ready": False, "reason": "Connection failed"}
            continue
        
        data = result['data']
        state = data.get('state', 'unknown')
        converting = data.get('converting', False)
        storage = data.get('storage', {})
        free_mb = storage.get('free_mb', 0)
        
        # Check if node is ready
        is_ready = True
        reason = None
        
        if state != 'idle':
            is_ready = False
            reason = f"Node is {state}"
        elif converting:
            is_ready = False
            reason = "Converting video"
        elif free_mb < 500:
            is_ready = False
            reason = f"Low storage ({free_mb} MB free, need 500 MB)"
        
        node_status[node_name] = {
            "ready": is_ready,
            "state": state,
            "converting": converting,
            "storage_free_mb": free_mb,
            "reason": reason if reason else "Ready"
        }
        
        if not is_ready:
            not_ready.append({
                "name": node_name,
                "ready": False,
                "reason": reason
            })
    
    # If any nodes not ready, return detailed error
    if not_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Nodes not ready",
                "ready": False,
                "details": node_status,
                "not_ready_nodes": not_ready
            }
        )
    
    # ========== ALL NODES READY - SCHEDULE RECORDING ==========
    
    # Calculate start time
    start_time = int(time.time()) + delay
    
    # Generate session ID based on start time
    from datetime import datetime
    dt = datetime.fromtimestamp(start_time)
    session_id = dt.strftime("session_%Y%m%d_%H%M%S")
    
    # Schedule all nodes
    schedule_results = await node_client.start_all_nodes(nodes, scheduled=start_time)
    
    # Build response
    nodes_response = []
    all_scheduled = True
    
    for result in schedule_results:
        node_name = result['node']
        success = result.get('success', False)
        
        nodes_response.append({
            "name": node_name,
            "ready": True,
            "scheduled": success,
            "data": result.get('data', {})
        })
        
        if not success:
            all_scheduled = False
    
    return {
        "start_time": start_time,
        "countdown": delay,
        "session_id": session_id,
        "ready": True,
        "all_scheduled": all_scheduled,
        "nodes": nodes_response
    }

@app.post("/recording/stop/synchronized")
async def stop_synchronized_recording():
    """
    Stop recording on all camera nodes immediately.
    
    Returns status of stop operation for each node.
    """
    import time
    
    nodes = load_nodes()
    
    # Stop all nodes in parallel
    stop_results = await node_client.stop_all_nodes(nodes)
    
    # Build response
    stopped_at = int(time.time())
    nodes_response = []
    
    for result in stop_results:
        node_name = result['node']
        success = result.get('success', False)
        
        nodes_response.append({
            "name": node_name,
            "stopped": success,
            "data": result.get('data', {}) if success else {"error": result.get('error')}
        })
    
    return {
        "stopped_at": stopped_at,
        "nodes": nodes_response
    }

@app.get("/recording/status")
async def get_recording_status():
    """
    Get current recording status across all nodes.
    
    Returns:
    - Overall recording state
    - Session ID if recording
    - Duration if recording
    - Individual node statuses
    """
    nodes = load_nodes()
    
    # Get status from all nodes
    status_results = await node_client.status_all_nodes(nodes)
    
    # Analyze results
    is_recording = False
    session_id = None
    max_duration = 0
    nodes_response = []
    
    for result in status_results:
        node_name = result['node']
        
        if not result['success']:
            nodes_response.append({
                "name": node_name,
                "state": "error",
                "error": result.get('error', 'Unable to connect')
            })
            continue
        
        data = result['data']
        state = data.get('state', 'unknown')
        node_recording = data.get('recording', False)
        node_session_id = data.get('session_id')
        duration = data.get('duration', 0)
        storage = data.get('storage', {})
        
        # Track if any node is recording
        if node_recording:
            is_recording = True
            if session_id is None:
                session_id = node_session_id
            max_duration = max(max_duration, duration)
        
        nodes_response.append({
            "name": node_name,
            "state": state,
            "recording": node_recording,
            "session_id": node_session_id,
            "duration": duration,
            "storage_free_mb": storage.get('free_mb', 0),
            "storage_percent_used": storage.get('used_percent', 0)
        })
    
    return {
        "recording": is_recording,
        "session_id": session_id,
        "duration": max_duration,
        "nodes": nodes_response
    }

# ========== BULK OPERATIONS (MUST BE BEFORE INDIVIDUAL ROUTES) ==========

@app.post("/nodes/all/start")
async def start_all_recordings(scheduled: Optional[int] = None):
    """Start recording on all nodes simultaneously"""
    nodes = load_nodes()
    results = await node_client.start_all_nodes(nodes, scheduled)
    return {"results": results}

@app.post("/nodes/all/stop")
async def stop_all_recordings():
    """Stop recording on all nodes simultaneously"""
    nodes = load_nodes()
    results = await node_client.stop_all_nodes(nodes)
    return {"results": results}

@app.get("/nodes/all/status")
async def get_all_status():
    """Get status from all nodes"""
    nodes = load_nodes()
    results = await node_client.status_all_nodes(nodes)
    return {"results": results}

# ========== INDIVIDUAL NODE CONTROL ==========

@app.get("/nodes/{node_name}/ready")
async def get_node_ready(node_name: str):
    """Check if node is ready to record"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_ready(nodes[node_name])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.get("/nodes/{node_name}/status")
async def get_node_status(node_name: str):
    """Get node recording status"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_status(nodes[node_name])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.get("/nodes/{node_name}/recordings")
async def get_node_recordings(node_name: str):
    """Get list of recordings from node"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_recordings(nodes[node_name])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.post("/nodes/{node_name}/start")
async def start_node_recording(node_name: str, scheduled: Optional[int] = None):
    """Start recording on a node"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_start_recording(nodes[node_name], scheduled)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.post("/nodes/{node_name}/stop")
async def stop_node_recording(node_name: str):
    """Stop recording on a node"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_stop_recording(nodes[node_name])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.delete("/nodes/{node_name}/scheduled")
async def cancel_node_scheduled(node_name: str):
    """Cancel scheduled recording on a node"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_cancel_scheduled(nodes[node_name])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.delete("/nodes/{node_name}/recordings/{session_id}")
async def delete_node_recording(node_name: str, session_id: str):
    """Delete a recording from a node"""
    nodes = load_nodes()
    
    if node_name not in nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    
    try:
        return await node_client.node_delete_recording(nodes[node_name], session_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {str(e)}")

@app.get("/recording/list")
async def list_all_recordings():
    """
    Get all recordings from all nodes, grouped by session.
    
    Shows which sessions have complete recordings (all nodes) vs incomplete.
    """
    nodes = load_nodes()
    
    # Get recordings from all nodes in parallel
    tasks = []
    for node_name, node_url in nodes.items():
        tasks.append(node_client.node_recordings(node_url))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Build a map: session_id -> {cam1: recording_data, cam2: recording_data}
    sessions = {}
    node_names = list(nodes.keys())
    
    for i, result in enumerate(results):
        node_name = node_names[i]
        
        if isinstance(result, Exception):
            continue
        
        recordings = result.get('recordings', [])
        
        for recording in recordings:
            session_id = recording.get('id') or recording.get('session_id')
            
            if session_id not in sessions:
                sessions[session_id] = {
                    'session_id': session_id,
                    'nodes': {},
                    'node_count': 0,
                    'complete': False
                }
            
            sessions[session_id]['nodes'][node_name] = recording
            sessions[session_id]['node_count'] += 1
    
    # Mark sessions as complete if all nodes have recordings
    total_nodes = len(nodes)
    for session_id, session_data in sessions.items():
        session_data['complete'] = (session_data['node_count'] == total_nodes)
        session_data['missing_nodes'] = [
            node for node in nodes.keys() 
            if node not in session_data['nodes']
        ]
    
    # Convert to list and sort by session_id (newest first)
    session_list = list(sessions.values())
    session_list.sort(key=lambda x: x['session_id'], reverse=True)
    
    return {
        'total_sessions': len(session_list),
        'total_nodes': total_nodes,
        'sessions': session_list
    }
