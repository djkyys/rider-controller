"""
OBD Service Client for main controller.
Communicates with separate OBD service on port 8001.
"""

import httpx
from typing import Optional
from config.logging_config import setup_logger

logger = setup_logger('obd_client')

OBD_SERVICE_URL = "http://localhost:8001"

class OBDClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=2.0)
        self.available = False
    
    async def check_available(self) -> bool:
        """Check if OBD service is running"""
        try:
            resp = await self.client.get(f"{OBD_SERVICE_URL}/")
            self.available = resp.status_code == 200
            return self.available
        except Exception as e:
            self.available = False
            logger.debug(f"OBD service check failed: {e}")
            return False
    
    async def get_current(self) -> Optional[dict]:
        """Get current OBD data snapshot"""
        if not self.available:
            await self.check_available()
            if not self.available:
                return None
        
        try:
            resp = await self.client.get(f"{OBD_SERVICE_URL}/current")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"Failed to get OBD current data: {e}")
            self.available = False
        return None
    
    async def get_health(self) -> Optional[dict]:
        """Get OBD service health status"""
        if not self.available:
            return None
        
        try:
            resp = await self.client.get(f"{OBD_SERVICE_URL}/health")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"Failed to get OBD health: {e}")
        return None
    
    async def get_commands(self) -> Optional[dict]:
        """Get list of available OBD commands"""
        if not self.available:
            return None
        
        try:
            resp = await self.client.get(f"{OBD_SERVICE_URL}/commands")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"Failed to get OBD commands: {e}")
        return None
    
    async def get_history(self, date: str = None) -> Optional[dict]:
        """Get historical OBD data for a specific date"""
        if not self.available:
            return None
        
        try:
            url = f"{OBD_SERVICE_URL}/history"
            if date:
                url += f"?date={date}"
            
            resp = await self.client.get(url)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"Failed to get OBD history: {e}")
        return None

# Global instance
obd_client = OBDClient()
