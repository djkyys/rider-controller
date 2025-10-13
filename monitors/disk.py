import psutil

async def get_disk_stats():
    disk = psutil.disk_usage('/')
    return {
        "total_gb": round(disk.total / (1024**3), 2),
        "free_gb": round(disk.free / (1024**3), 2),
        "used_percent": disk.percent
    }
