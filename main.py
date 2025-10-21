from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
import json
import asyncio
from typing import Optional, Set
from datetime import datetime

# Setup unified logging
from config.logging_config import setup_logger
logger = setup_logger('main')

app = FastAPI()

# ========== WEBSOCKET CONNECTION MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.last_status = None
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
        
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
        
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return
            
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
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
    
    async def send_obd_update(self, obd_data: dict):
        """Send OBD update to all clients"""
        message = {
            "type": "obd_update",
            "timestamp": int(datetime.now().timestamp()),
            "data": obd_data
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
        
        # Also log it
        if severity == "error":
            logger.error(f"Node {node}: {error_message}")
        else:
            logger.warning(f"Node {node}: {error_message}")
    
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

# ========== OBD INTEGRATION ==========

from obd_client import obd_client

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
    return str(datetime.now())

# ========== OBD ENDPOINTS (PROXIED) ==========

@app.get("/obd/status")
async def get_obd_status():
    """Check if OBD service is available"""
    available = await obd_client.check_available()
    return {
        "available": available,
        "service": "OBD-II Logger"
    }

@app.get("/obd/current")
async def get_obd_current():
    """Get current OBD data"""
    data = await obd_client.get_current()
    if data is None:
        raise HTTPException(status_code=503, detail="OBD service unavailable")
    return data

@app.get("/obd/health")
async def get_obd_health():
    """Get OBD service health"""
    data = await obd_client.get_health()
    if data is None:
        raise HTTPException(status_code=503, detail="OBD service unavailable")
    return data

@app.get("/obd/commands")
async def get_obd_commands():
    """Get available OBD commands"""
    data = await obd_client.get_commands()
    if data is None:
        raise HTTPException(status_code=503, detail="OBD service unavailable")
    return data

# ========== WEBSOCKET ENDPOINT ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    
    Sends:
    - status_update: When recording state changes
    - health_update: Every 3 seconds (camera nodes)
    - obd_update: Every 2 seconds (vehicle data)
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
        logger.error(f"WebSocket error: {e}")
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
            logger.error(f"Health monitor error: {e}")
            await asyncio.sleep(3)

async def obd_websocket_monitor():
    """Background task to poll OBD and broadcast via WebSocket"""
    await asyncio.sleep(5)  # Wait for startup
    
    # Check if OBD service is available
    if not await obd_client.check_available():
        logger.warning("OBD service not available - OBD monitoring disabled")
        return
    
    logger.info("OBD WebSocket monitoring started")
    
    while True:
        try:
            await asyncio.sleep(2)  # Poll every 2 seconds
            
            if not manager.active_connections:
                continue  # Skip if no clients
            
            # Get current OBD data
            obd_data = await obd_client.get_current()
            
            if obd_data:
                # Extract key metrics for WebSocket (don't send everything)
                simplified_data = {
                    "timestamp": obd_data.get("timestamp"),
                    "speed": obd_data.get("SPEED", {}).get("value") if "SPEED" in obd_data else None,
                    "rpm": obd_data.get("RPM", {}).get("value") if "RPM" in obd_data else None,
                    "coolant_temp": obd_data.get("COOLANT_TEMP", {}).get("value") if "COOLANT_TEMP" in obd_data else None,
                    "throttle": obd_data.get("THROTTLE_POS", {}).get("value") if "THROTTLE_POS" in obd_data else None,
                }
                
                # Broadcast to WebSocket clients
                await manager.send_obd_update(simplified_data)
                
        except Exception as e:
            logger.error(f"OBD WebSocket monitor error: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    """Start background tasks"""
    logger.info("=" * 60)
    logger.info("Rider Controller Starting")
    logger.info("=" * 60)
    
    # Start health monitoring
    asyncio.create_task(health_monitor())
    logger.info("✓ Health monitor started")
    
    # Check OBD availability and start monitoring if available
    obd_available = await obd_client.check_available()
    if obd_available:
        logger.info("✓ OBD service connected")
        asyncio.create_task(obd_websocket_monitor())
        logger.info("✓ OBD WebSocket monitor started")
    else:
        logger.warning("✗ OBD service not available (non-critical)")

# ========== STORAGE MANAGEMENT ==========

@app.get("/storage/status")
async def get_storage_status():
    """Get storage status across all devices"""
    
    nodes = load_nodes()
    status_results = await node_client.status_all_nodes(nodes)
    
    storage_status = {
        "overall_status": "ok",  # ok, warning, critical
        "can_record": True,
        "devices": []
    }
    
    # Check camera nodes
    for result in status_results:
        node_name = result['node']
        if result['success']:
            free_mb = result['data'].get('storage', {}).get('free_mb', 0)
            total_mb = result['data'].get('storage', {}).get('total_mb', 0)
            used_percent = result['data'].get('storage', {}).get('used_percent', 0)
            
            status = "ok"
            can_record = True
            
            min_required = MIN_FREE_MB.get(node_name, MIN_FREE_MB['cam1'])
            warning_threshold = WARNING_FREE_MB.get(node_name, WARNING_FREE_MB['cam1'])
            
            if free_mb < min_required:
                status = "critical"
                can_record = False
                storage_status["can_record"] = False
                storage_status["overall_status"] = "critical"
            elif free_mb < warning_threshold:
                status = "warning"
                if storage_status["overall_status"] == "ok":
                    storage_status["overall_status"] = "warning"
            
            storage_status["devices"].append({
                "name": node_name,
                "type": "camera",
                "free_mb": round(free_mb, 0),
                "total_mb": round(total_mb, 0),
                "used_percent": round(used_percent, 1),
                "status": status,
                "can_record": can_record,
                "min_required_mb": min_required,
                "estimated_recording_time_minutes": max(0, (free_mb - min_required) / 2)  # ~2MB/min
            })
    
    # Check main Pi
    disk = shutil.disk_usage('/')
    free_mb = disk.free / (1024**2)
    total_mb = disk.total / (1024**2)
    used_percent = (disk.used / disk.total) * 100
    
    status = "ok"
    can_record = True
    
    if free_mb < MIN_FREE_MB['main_pi']:
        status = "critical"
        can_record = False
        storage_status["can_record"] = False
        storage_status["overall_status"] = "critical"
    elif free_mb < WARNING_FREE_MB['main_pi']:
        status = "warning"
        if storage_status["overall_status"] == "ok":
            storage_status["overall_status"] = "warning"
    
    storage_status["devices"].append({
        "name": "main_pi",
        "type": "main_controller",
        "free_mb": round(free_mb, 0),
        "total_mb": round(total_mb, 0),
        "used_percent": round(used_percent, 1),
        "status": status,
        "can_record": can_record,
        "min_required_mb": MIN_FREE_MB['main_pi'],
        "estimated_recording_time_minutes": max(0, (free_mb - MIN_FREE_MB['main_pi']) / 0.1)  # ~0.1MB/min OBD
    })
    
    return storage_status

# ========== SESSION MANAGEMENT ==========

@app.get("/sessions/list")
async def list_sessions(limit: int = 100, offset: int = 0):
    """List all recording sessions"""
    session_dir = Path("/home/pi/rider-data/sessions")
    
    if not session_dir.exists():
        return {"sessions": [], "total": 0}
    
    sessions = []
    for session_path in sorted(session_dir.iterdir(), reverse=True):
        if session_path.is_dir():
            metadata_file = session_path / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        sessions.append(metadata)
                except Exception as e:
                    logger.error(f"Error reading metadata for {session_path.name}: {e}")
    
    total = len(sessions)
    sessions = sessions[offset:offset+limit]
    
    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get details of a specific session"""
    session_path = Path(f"/home/pi/rider-data/sessions/{session_id}")
    metadata_file = session_path / "metadata.json"
    
    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    
    with open(metadata_file) as f:
        return json.load(f)

@app.get("/sessions/stats")
async def get_session_stats():
    """Get overall session statistics"""
    session_dir = Path("/home/pi/rider-data/sessions")
    
    if not session_dir.exists():
        return {"total_sessions": 0, "total_size_gb": 0}
    
    sessions = list(session_dir.iterdir())
    total_sessions = len(sessions)
    
    if total_sessions == 0:
        return {"total_sessions": 0, "total_size_gb": 0, "average_size_mb": 0}
    
    total_size = 0
    for session in sessions:
        if session.is_dir():
            for f in session.rglob('*'):
                if f.is_file():
                    total_size += f.stat().st_size
    
    return {
        "total_sessions": total_sessions,
        "total_size_gb": round(total_size / (1024**3), 2),
        "average_size_mb": round((total_size / total_sessions) / (1024**2), 2) if total_sessions > 0 else 0
    }

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
    logger.info(f"Node registered: {node_name} -> {node_url}")
    return {"message": f"Node {node_name} registered", "url": node_url}

# ========== SYNCHRONIZED RECORDING API ==========

@app.post("/recording/start/synchronized")
async def start_synchronized_recording(delay: int = 5, session_id: Optional[str] = None):
    """Start synchronized recording across all camera nodes."""
    import time
    import uuid
    
    logger.info(f"Synchronized recording start requested (delay={delay}s)")
    
    # Generate session ID if not provided (format: 20241215_143052_A1B2C3D4)
    if not session_id:
        session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"
        logger.info(f"Generated session ID: {session_id}")
    else:
        logger.info(f"Using provided session ID: {session_id}")
    
    # Get OBD data at recording start
    obd_data = await obd_client.get_current()
    if obd_data:
        speed = obd_data.get("SPEED", {}).get("value", 0)
        logger.info(f"Recording starting at {speed} km/h")
    
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
            logger.warning(f"Node {node_name} not ready: Connection failed")
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
        elif free_mb < 1000:  # Require 1GB free
            is_ready = False
            reason = f"Low storage ({free_mb} MB free, need 1000 MB)"
        
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
            logger.warning(f"Node {node_name} not ready: {reason}")
    
    if not_ready:
        logger.error("Cannot start recording - some nodes not ready")
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
    
    logger.info(f"Scheduling recording - Session: {session_id}, Start: {start_time}")
    
    # Schedule all nodes
    schedule_results = await node_client.start_all_nodes(nodes, scheduled=start_time, session_id=session_id)
    obd_start = await obd_client.start_session(session_id)
    
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
            logger.error(f"Failed to schedule {node_name}")
        else:
            logger.info(f"✓ Scheduled {node_name}")
    
    return {
        "session_id": session_id,
        "start_time": start_time,
        "countdown": delay,
        "ready": True,
        "all_scheduled": all_scheduled,
        "nodes": nodes_response,
        "obd_snapshot": {"started": obd_start is not None}
    }

@app.post("/recording/stop/synchronized")
async def stop_synchronized_recording():
    """Stop recording on all nodes immediately."""
    import time
    
    logger.info("Synchronized recording stop requested")
    
    nodes = load_nodes()
    stop_results = await node_client.stop_all_nodes(nodes)
    obd_stop = await obd_client.stop_session()
    
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
        
        if success:
            logger.info(f"✓ Stopped {node_name}")
        else:
            logger.error(f"Failed to stop {node_name}")
    
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
        "nodes": nodes_response,
        "obd_snapshot": {"stopped success": obd_stop is not None} # Include OBD data at recording stop
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

# ========== BULK OPERATIONS ==========

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
