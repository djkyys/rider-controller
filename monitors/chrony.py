import subprocess
import re
from typing import Dict, List

async def get_chrony_tracking() -> Dict:
    """Get detailed chrony tracking information"""
    try:
        result = subprocess.run(['chronyc', 'tracking'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        
        if result.returncode != 0:
            return {"error": "Failed to get tracking info"}
        
        output = result.stdout
        tracking = {}
        
        # Parse tracking output
        patterns = {
            'reference_id': r'Reference ID\s+:\s+(\S+)',
            'stratum': r'Stratum\s+:\s+(\d+)',
            'ref_time': r'Ref time \(UTC\)\s+:\s+(.+)',
            'system_time': r'System time\s+:\s+([\d.]+)\s+seconds\s+(\w+)',
            'last_offset': r'Last offset\s+:\s+([\-+\d.]+)\s+seconds',
            'rms_offset': r'RMS offset\s+:\s+([\d.]+)\s+seconds',
            'frequency': r'Frequency\s+:\s+([\-+\d.]+)\s+ppm',
            'residual_freq': r'Residual freq\s+:\s+([\-+\d.]+)\s+ppm',
            'skew': r'Skew\s+:\s+([\d.]+)\s+ppm',
            'root_delay': r'Root delay\s+:\s+([\d.]+)\s+seconds',
            'root_dispersion': r'Root dispersion\s+:\s+([\d.]+)\s+seconds',
            'update_interval': r'Update interval\s+:\s+([\d.]+)\s+seconds',
            'leap_status': r'Leap status\s+:\s+(.+)'
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                if key == 'system_time':
                    tracking['system_time_offset'] = float(match.group(1))
                    tracking['system_time_direction'] = match.group(2)
                else:
                    tracking[key] = match.group(1)
        
        return tracking
        
    except subprocess.TimeoutExpired:
        return {"error": "Chrony tracking timeout"}
    except Exception as e:
        return {"error": str(e)}

async def get_chrony_sources() -> List[Dict]:
    """Get list of NTP sources"""
    try:
        result = subprocess.run(['chronyc', 'sources'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        
        if result.returncode != 0:
            return []
        
        sources = []
        lines = result.stdout.strip().split('\n')
        
        # Skip header lines (first 2-3 lines)
        data_lines = [l for l in lines if l.startswith('^') or l.startswith('=')]
        
        for line in data_lines:
            parts = line.split()
            if len(parts) >= 9:
                source = {
                    'state': parts[0][0],  # '^' or '='
                    'mode': parts[0][1] if len(parts[0]) > 1 else '',
                    'name': parts[1],
                    'stratum': int(parts[2]) if parts[2].isdigit() else 0,
                    'poll': int(parts[3]) if parts[3].isdigit() else 0,
                    'reach': parts[4],
                    'last_rx': parts[5],
                    'last_sample_offset': parts[6],
                    'last_sample_measured': parts[7] if len(parts) > 7 else None
                }
                sources.append(source)
        
        return sources
        
    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        return []

async def get_chrony_clients() -> List[Dict]:
    """Get list of NTP clients (nodes syncing to this server)"""
    try:
        result = subprocess.run(['chronyc', 'clients'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        
        if result.returncode != 0:
            return []
        
        clients = []
        lines = result.stdout.strip().split('\n')
        
        # Skip header
        for line in lines[2:]:
            if not line.strip():
                continue
                
            parts = line.split()
            if len(parts) >= 6:
                client = {
                    'hostname': parts[0],
                    'ntp_packets': int(parts[1]) if parts[1].isdigit() else 0,
                    'cmd_packets': int(parts[2]) if parts[2].isdigit() else 0,
                    'ntp_drop': int(parts[3]) if parts[3].isdigit() else 0,
                    'cmd_drop': int(parts[4]) if parts[4].isdigit() else 0,
                    'last_ntp': parts[5] if len(parts) > 5 else None
                }
                clients.append(client)
        
        return clients
        
    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        return []

async def get_chrony_stats() -> Dict:
    """Get comprehensive chrony statistics"""
    try:
        tracking = await get_chrony_tracking()
        sources = await get_chrony_sources()
        clients = await get_chrony_clients()
        
        # Determine sync status
        synced = False
        if 'stratum' in tracking:
            try:
                stratum = int(tracking['stratum'])
                synced = (1 <= stratum <= 15)
            except:
                pass
        
        # Get current server as master info
        is_master = len(clients) > 0
        
        return {
            'synced': synced,
            'is_master': is_master,
            'tracking': tracking,
            'sources': sources,
            'clients': clients,
            'client_count': len(clients)
        }
        
    except Exception as e:
        return {
            'error': str(e),
            'synced': False,
            'is_master': False
        }
