"""
OBD Service Client - Async wrapper for OBD service API calls
"""
import aiohttp
import asyncio
from typing import Dict, Optional

# OBD service location
OBD_SERVICE_URL = "http://localhost:8001"

class OBDClient:
    def __init__(self, base_url: str = OBD_SERVICE_URL):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=5)
    
    async def check_available(self) -> bool:
        """Check if OBD service is available"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/health") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("healthy", False)
                    return False
        except Exception:
            return False
    
    async def get_current(self) -> Optional[Dict]:
        """Get current OBD data snapshot"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/current") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None
    
    async def get_health(self) -> Optional[Dict]:
        """Get OBD service health status"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/health") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None
    
    async def get_commands(self) -> Optional[Dict]:
        """Get available OBD commands"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/commands") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None
    
    async def get_session_status(self) -> Optional[Dict]:
        """Get current session status"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/session") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None
    
    async def start_session(self, session_id: str) -> Optional[Dict]:
        """Start OBD logging session"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/session/start",
                    json={"session_id": session_id}
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"Error starting OBD session: {e}")
            return None
    
    async def stop_session(self) -> Optional[Dict]:
        """Stop current OBD logging session"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(f"{self.base_url}/session/stop") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"Error stopping OBD session: {e}")
            return None
    
    async def list_sessions(self) -> Optional[Dict]:
        """List all OBD session log files"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/sessions") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None
    
    async def get_session_history(self, session_id: str) -> Optional[Dict]:
        """Get historical OBD data for a specific session"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/history/{session_id}") as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception:
            return None

# Global instance
obd_client = OBDClient()
