from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
import json
import asyncio
from typing import Optional, Set
from datetime import datetime

app = FastAPI()

# ========== WEBSOCKET CONNECTION MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.last_status = None
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"✓ WebSocket connected. Total connections: {len(self.active_connections)}")
        
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        print(f"✗ WebSocket disconnected. Total connections: {len(self.active_connections)}")
        
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return
            
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error sending to client: {e}")
                disconnected.add(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection)
    
    async def send_status_update(self, status_data: dict):
        """Send status update to all clients"""
        message = {
            "type": "status_update",
            "timestamp": int(datetime.now().timestamp()),
            "data": status_data
        }
        self.last_status = status_data
        await self.broadcast(message)
    
    async def send_health_update(self, health_data: dict):
        """Send health update to all clients"""
        message = {
            "type": "health_update",
            "timestamp": int(datetime.now().timestamp()),
            "data": health_data
        }
        await self.broadcast(message)
    
    async def send_error(self, error_message: str, severity: str = "warning", node: str = None):
        """Send error/warning to all clients"""
        message = {
            "type": "error",
            "timestamp": int(datetime.now().timestamp()),
            "severity": severity,
            "node": node,
            "message": error_message
        }
        await self.broadcast(message)
    
    async def send_ping(self):
        """Send keep-alive ping"""
        message = {
            "type": "ping",
            "timestamp": int(datetime.now().timestamp())
        }
        await self.broadcast(message)

manager = ConnectionManager()

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

# ========== WEBSOCKET ENDPOINT ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    
    Sends:
    - status_update: When recording state changes
    - health_update: Every 3 seconds
    - ping: Keep-alive every 30 seconds
    - error: Warnings and errors
    """
    await manager.connect(websocket)
    
    try:
        # Send initial status
        if manager.last_status:
            await websocket.send_json({
                "type": "status_update",
                "timestamp": int(datetime.now().timestamp()),
                "data": manager.last_status
            })
        
        # Keep connection alive and listen for messages
        while True:
            try:
                # Wait for message with timeout (ping interval)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                # Handle client messages (if any)
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": int(datetime.now().timestamp())
                        })
                except json.JSONDecodeError:
                    pass
                    
            except asyncio.TimeoutError:
                # Send keep-alive ping
                await manager.send_ping()
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# ========== BACKGROUND TASKS ==========

async def health_monitor():
    """Background task to monitor node health and send updates via WebSocket"""
    while True:
        try:
            await asyncio.sleep(3)  # Every 3 seconds
            
            if not manager.active_connections:
                continue  # Skip if no clients connected
            
            nodes = load_nodes()
            status_results = await node_client.status_all_nodes(nodes)
            
            health_data = {
                "nodes": []
            }
            
            for result in status_results:
                node_name = result['node']
                
                if not result['success']:
                    health_data['nodes'].append({
                        "name": node_name,
                        "connected": False,
                        "error": result.get('error', 'Unable to connect')
                    })
                    continue
                
                data = result['data']
                storage = data.get('storage', {})
                free_mb = storage.get('free_mb', 0)
                
                node_health = {
                    "name": node_name,
                    "connected": True,
                    "state": data.get('state', 'unknown'),
                    "storage_free_mb": free_mb,
                    "storage_percent_used": storage.get('used_percent', 0)
                }
                
                # Add recording info if recording
                if data.get('recording'):
                    node_health['recording'] = True
                    node_health['duration'] = data.get('duration', 0)
                    node_health['session_id'] = data.get('session_id')
                
                health_data['nodes'].append(node_health)
                
                # Check for low storage warning
                if free_mb > 0 and free_mb < 500:
                    await manager.send_error(
                        f"Low storage: {free_mb} MB remaining",
                        severity="warning",
                        node=node_name
                    )
            
            await manager.send_health_update(health_data)
            
        except Exception as e:
            print(f"Health monitor error: {e}")
            await asyncio.sleep(3)

@app.on_event("startup")
async def startup_event():
    """Start background tasks"""
    asyncio.create_task(health_monitor())

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
    """Start synchronized recording across all camera nodes."""
    import time
    
    # Validate delay
    if delay < 2:
        raise HTTPException(status_code=400, detail="Minimum delay is 2 seconds")
    if delay > 30:
        raise HTTPException(status_code=400, detail="Maximum delay is 30 seconds")
    
    nodes = load_nodes()
    
    # Pre-flight checks
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
    
    # Calculate start time
    start_time = int(time.time()) + delay
    
    # Generate session ID
    from datetime import datetime
    dt = datetime.fromtimestamp(start_time)
    session_id = dt.strftime("session_%Y%m%d_%H%M%S")
    
    # Schedule all nodes
    schedule_results = await node_client.start_all_nodes(nodes, scheduled=start_time)
    
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
    """Stop recording on all nodes immediately."""
    import time
    
    nodes = load_nodes()
    stop_results = await node_client.stop_all_nodes(nodes)
    
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
    
    # Broadcast stop event via WebSocket
    await manager.send_status_update({
        "recording": False,
        "session_id": None,
        "duration": 0,
        "stopped_at": stopped_at,
        "nodes": nodes_response
    })
    
    return {
        "stopped_at": stopped_at,
        "nodes": nodes_response
    }

@app.get("/recording/status")
async def get_recording_status():
    """Get current recording status across all nodes."""
    nodes = load_nodes()
    status_results = await node_client.status_all_nodes(nodes)
    
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
    
    status_data = {
        "recording": is_recording,
        "session_id": session_id,
        "duration": max_duration,
        "nodes": nodes_response
    }
    
    # Update last status for WebSocket
    manager.last_status = status_data
    
    return status_data

@app.get("/recording/list")
async def list_all_recordings():
    """Get all recordings from all nodes, grouped by session."""
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
