import psutil
import time

start_time = time.time()

async def get_health_status():
    return {
        "status": "healthy",
        "uptime_seconds": round(time.time() - start_time),
        "load_average": psutil.getloadavg()
    }
