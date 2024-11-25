# services/host/monitor.py

import psutil
import platform
import socket
import os
from datetime import datetime
import logging
from typing import Dict, List

class HostMonitor:
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def get_host_details(self) -> Dict:
        """Get comprehensive host system information"""
        try:
            return {
                'timestamp': datetime.now(),
                'hostname': socket.gethostname(),
                'os': f"{platform.system()} {platform.release()}",
                'kernel': platform.version(),
                'arch': platform.machine(),
                'uptime': self.get_uptime(),
                'boot_time': datetime.fromtimestamp(psutil.boot_time()),
                'cpu': self.get_cpu_info(),
                'memory': self.get_memory_info(),
                'disks': self.get_disk_info(),
                'networks': self.get_network_info(),
                'process_count': len(psutil.pids()),
                'users_count': len(psutil.users())
            }
        except Exception as e:
            self.logger.error(f"Error getting host details: {str(e)}")
            raise

    def get_uptime(self) -> float:
        """Get system uptime in seconds"""
        return (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds()

    def get_cpu_info(self) -> Dict:
        """Get detailed CPU information"""
        cpu_freq = psutil.cpu_freq()
        return {
            'cores_physical': psutil.cpu_count(logical=False),
            'cores_logical': psutil.cpu_count(logical=True),
            'usage_percent': psutil.cpu_percent(interval=1),
            'per_cpu_percent': psutil.cpu_percent(interval=1, percpu=True),
            'load_avg_1m': psutil.getloadavg()[0],
            'load_avg_5m': psutil.getloadavg()[1],
            'load_avg_15m': psutil.getloadavg()[2],
            'frequency_current': cpu_freq.current if cpu_freq else 0,
            'frequency_min': cpu_freq.min if cpu_freq else 0,
            'frequency_max': cpu_freq.max if cpu_freq else 0
        }

    def get_memory_info(self) -> Dict:
        """Get detailed memory information"""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            'total': mem.total / (1024**3),  # Convert to GB
            'available': mem.available / (1024**3),
            'used': mem.used / (1024**3),
            'free': mem.free / (1024**3),
            'percent_used': mem.percent,
            'swap_total': swap.total / (1024**3),
            'swap_used': swap.used / (1024**3),
            'swap_free': swap.free / (1024**3),
            'swap_percent': swap.percent
        }

    def get_disk_info(self) -> List[Dict]:
        """Get detailed disk information"""
        disks = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disks.append({
                    'device': partition.device,
                    'mount_point': partition.mountpoint,
                    'fs_type': partition.fstype,
                    'total_size': usage.total / (1024**3),  # Convert to GB
                    'used': usage.used / (1024**3),
                    'free': usage.free / (1024**3),
                    'percent_used': usage.percent
                })
            except (PermissionError, OSError):
                continue
        return disks

    def get_network_info(self) -> List[Dict]:
        """Get detailed network interface information"""
        networks = []
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        net_io_counters = psutil.net_io_counters(pernic=True)

        for interface_name, addrs in net_if_addrs.items():
            if interface_name != 'lo':  # Skip loopback
                interface = {
                    'name': interface_name,
                    'ip_address': '',
                    'mac_address': '',
                    'netmask': ''
                }

                # Get addresses
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        interface['ip_address'] = addr.address
                        interface['netmask'] = addr.netmask
                    elif addr.family == psutil.AF_LINK:
                        interface['mac_address'] = addr.address

                # Get stats if available
                if interface_name in net_if_stats:
                    stats = net_if_stats[interface_name]
                    interface['speed'] = stats.speed if stats.speed > 0 else None

                # Get IO counters if available
                if interface_name in net_io_counters:
                    counters = net_io_counters[interface_name]
                    interface.update({
                        'bytes_sent': counters.bytes_sent,
                        'bytes_recv': counters.bytes_recv,
                        'packets_sent': counters.packets_sent,
                        'packets_recv': counters.packets_recv,
                        'errors_in': counters.errin,
                        'errors_out': counters.errout
                    })

                networks.append(interface)

        return networks