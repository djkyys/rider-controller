import psutil
import os

async def get_cpu_stats():
    # Get CPU temperature (Raspberry Pi)
    try:
        temp = psutil.sensors_temperatures()
        cpu_temp = temp['cpu_thermal'][0].current if 'cpu_thermal' in temp else None
    except:
        cpu_temp = None
    
    return {
        "usage_percent": psutil.cpu_percent(interval=0.1),
        "temperature": cpu_temp,
        "cores": psutil.cpu_count()
    }
