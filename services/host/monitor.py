# services/host/monitor.py

import psutil
import platform
import sqlite3
from datetime import datetime
import socket
from typing import Dict, List
import logging

class HostMonitor:
    """Service for monitoring host system metrics"""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._excluded_mounts = {'/dev', '/sys', '/proc', '/run', '/snap'}
        self._excluded_filesystems = {'squashfs', 'tmpfs', 'devtmpfs'}

    def get_host_info(self) -> Dict:
        """Get basic host system information"""
        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            return {
                'hostname': socket.gethostname(),
                'os': f"{platform.system()} {platform.release()}",
                'uptime': (datetime.now() - boot_time).total_seconds(),
                'boot_time': boot_time
            }
        except Exception as e:
            self.logger.error(f"Error getting host info: {str(e)}")
            return {}

    def get_cpu_metrics(self) -> Dict:
        """Get CPU usage metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            cpu_avg = sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0
            
            return {
                'count': psutil.cpu_count(),
                'percent': round(cpu_avg, 2),
                'per_cpu': [round(x, 2) for x in cpu_percent],
                'load_avg': [round(x, 2) for x in psutil.getloadavg()]
            }
        except Exception as e:
            self.logger.error(f"Error getting CPU metrics: {str(e)}")
            return {}

    def get_memory_metrics(self) -> Dict:
        """Get memory usage metrics"""
        try:
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            return {
                'total': round(vm.total / (1024**3), 2),  # GB
                'available': round(vm.available / (1024**3), 2),
                'used': round(vm.used / (1024**3), 2),
                'free': round(vm.free / (1024**3), 2),
                'percent_used': vm.percent,
                'swap_total': round(swap.total / (1024**3), 2),
                'swap_used': round(swap.used / (1024**3), 2),
                'swap_percent': swap.percent
            }
        except Exception as e:
            self.logger.error(f"Error getting memory metrics: {str(e)}")
            return {}

    def get_disk_metrics(self) -> List[Dict]:
        """Get disk usage metrics"""
        try:
            disk_partitions = psutil.disk_partitions()
            disk_metrics = []
            
            for partition in disk_partitions:
                # Skip excluded mounts and filesystems
                if (partition.mountpoint in self._excluded_mounts or
                    partition.fstype in self._excluded_filesystems):
                    continue
                    
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_metrics.append({
                        'device': partition.device,
                        'total': round(usage.total / (1024**3), 2),  # GB
                        'used': round(usage.used / (1024**3), 2),
                        'free': round(usage.free / (1024**3), 2),
                        'percent_used': usage.percent,
                        'mount_point': partition.mountpoint
                    })
                except PermissionError:
                    continue
                
            return disk_metrics
        except Exception as e:
            self.logger.error(f"Error getting disk metrics: {str(e)}")
            return []

    def get_network_metrics(self) -> List[Dict]:
        """Get network interface metrics"""
        try:
            net_io_counters = psutil.net_io_counters(pernic=True)
            net_metrics = []
            
            for interface, counters in net_io_counters.items():
                # Skip loopback
                if interface == 'lo':
                    continue
                    
                net_metrics.append({
                    'interface': interface,
                    'bytes_sent': round(counters.bytes_sent / (1024**2), 2),  # MB
                    'bytes_recv': round(counters.bytes_recv / (1024**2), 2),
                    'packets_sent': counters.packets_sent,
                    'packets_recv': counters.packets_recv,
                    'errors_in': counters.errin,
                    'errors_out': counters.errout
                })
                
            return net_metrics
        except Exception as e:
            self.logger.error(f"Error getting network metrics: {str(e)}")
            return []

    def get_all_metrics(self) -> Dict:
        """Get all host system metrics"""
        return {
            'timestamp': datetime.now(),
            'host_info': self.get_host_info(),
            'cpu': self.get_cpu_metrics(),
            'memory': self.get_memory_metrics(),
            'disks': self.get_disk_metrics(),
            'network': self.get_network_metrics()
        }

    def log_metrics(self) -> None:
        """Log current host metrics to database"""
        try:
            metrics = self.get_all_metrics()
            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            
            # Insert host metrics
            cursor.execute('''
                INSERT INTO host_metrics (
                    timestamp,
                    cpu_percent,
                    cpu_count,
                    load_avg_1m,
                    load_avg_5m,
                    load_avg_15m,
                    memory_total,
                    memory_used,
                    memory_percent,
                    swap_total,
                    swap_used,
                    swap_percent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metrics['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                metrics['cpu']['percent'],
                metrics['cpu']['count'],
                metrics['cpu']['load_avg'][0],
                metrics['cpu']['load_avg'][1],
                metrics['cpu']['load_avg'][2],
                metrics['memory']['total'],
                metrics['memory']['used'],
                metrics['memory']['percent_used'],
                metrics['memory']['swap_total'],
                metrics['memory']['swap_used'],
                metrics['memory']['swap_percent']
            ))
            
            # Log disk metrics
            for disk in metrics['disks']:
                cursor.execute('''
                    INSERT INTO disk_metrics (
                        timestamp,
                        device,
                        total,
                        used,
                        free,
                        percent_used,
                        mount_point
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    metrics['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                    disk['device'],
                    disk['total'],
                    disk['used'],
                    disk['free'],
                    disk['percent_used'],
                    disk['mount_point']
                ))
            
            # Log network metrics
            for net in metrics['network']:
                cursor.execute('''
                    INSERT INTO network_metrics (
                        timestamp,
                        interface,
                        bytes_sent,
                        bytes_recv,
                        packets_sent,
                        packets_recv,
                        errors_in,
                        errors_out
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    metrics['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                    net['interface'],
                    net['bytes_sent'],
                    net['bytes_recv'],
                    net['packets_sent'],
                    net['packets_recv'],
                    net['errors_in'],
                    net['errors_out']
                ))
            
            conn.commit()
            self.logger.info("Host metrics logged successfully")
            
        except Exception as e:
            self.logger.error(f"Error logging host metrics: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()