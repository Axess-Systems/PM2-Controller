# api/routes/host.py

from datetime import datetime, timedelta
from flask import request
from flask_restx import Resource

def create_host_routes(namespace, services):
    """Create routes for host system monitoring"""
    
    @namespace.route('/metrics')
    class HostMetrics(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.host_monitor = services['host_monitor']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: 'Success',
                500: 'Internal server error'
            }
        )
        @namespace.marshal_with(namespace.models['host_metrics'])
        def get(self):
            """Get current host system metrics"""
            try:
                return self.host_monitor.get_all_metrics()
            except Exception as e:
                self.logger.error(f"Error getting host metrics: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")

# api/routes/host.py (continued)

    @namespace.route('/historical')
    class HostHistorical(Resource):
        def _get_historical_metrics(self, start_time, end_time, interval):
            """Get historical host metrics with aggregation"""
            conn = sqlite3.connect(self.config.DB_PATH)
            try:
                cursor = conn.cursor()
                
                # Get host metrics
                cursor.execute('''
                    WITH intervals AS (
                        SELECT 
                            strftime('%Y-%m-%d %H:%M:00', timestamp) as interval_start,
                            AVG(cpu_percent) as avg_cpu,
                            MAX(cpu_percent) as max_cpu,
                            AVG(memory_percent) as avg_memory,
                            MAX(memory_percent) as max_memory,
                            AVG(swap_percent) as avg_swap,
                            MAX(load_avg_1m) as max_load_1m,
                            MAX(load_avg_5m) as max_load_5m,
                            MAX(load_avg_15m) as max_load_15m
                        FROM host_metrics 
                        WHERE timestamp BETWEEN ? AND ?
                        GROUP BY interval_start
                        ORDER BY interval_start ASC
                    )
                    SELECT * FROM intervals
                ''', (
                    start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                host_rows = cursor.fetchall()
                
                # Get disk metrics
                cursor.execute('''
                    WITH intervals AS (
                        SELECT 
                            strftime('%Y-%m-%d %H:%M:00', timestamp) as interval_start,
                            device,
                            AVG(percent_used) as avg_usage,
                            MAX(percent_used) as max_usage,
                            AVG(free) as avg_free
                        FROM disk_metrics 
                        WHERE timestamp BETWEEN ? AND ?
                        GROUP BY interval_start, device
                        ORDER BY interval_start ASC
                    )
                    SELECT * FROM intervals
                ''', (
                    start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                disk_rows = cursor.fetchall()
                
                # Get network metrics
                cursor.execute('''
                    WITH intervals AS (
                        SELECT 
                            strftime('%Y-%m-%d %H:%M:00', timestamp) as interval_start,
                            interface,
                            SUM(bytes_sent) as total_sent,
                            SUM(bytes_recv) as total_recv,
                            SUM(errors_in + errors_out) as total_errors
                        FROM network_metrics 
                        WHERE timestamp BETWEEN ? AND ?
                        GROUP BY interval_start, interface
                        ORDER BY interval_start ASC
                    )
                    SELECT * FROM intervals
                ''', (
                    start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                network_rows = cursor.fetchall()
                
                return {
                    'timestamps': [row[0] for row in host_rows],
                    'cpu': {
                        'average': [float(row[1]) if row[1] is not None else 0.0 for row in host_rows],
                        'max': [float(row[2]) if row[2] is not None else 0.0 for row in host_rows],
                        'load_averages': {
                            '1m': [float(row[6]) if row[6] is not None else 0.0 for row in host_rows],
                            '5m': [float(row[7]) if row[7] is not None else 0.0 for row in host_rows],
                            '15m': [float(row[8]) if row[8] is not None else 0.0 for row in host_rows]
                        }
                    },
                    'memory': {
                        'average': [float(row[3]) if row[3] is not None else 0.0 for row in host_rows],
                        'max': [float(row[4]) if row[4] is not None else 0.0 for row in host_rows],
                        'swap': [float(row[5]) if row[5] is not None else 0.0 for row in host_rows]
                    },
                    'disks': self._format_disk_metrics(disk_rows),
                    'network': self._format_network_metrics(network_rows)
                }
                
            finally:
                conn.close()

        def _format_disk_metrics(self, rows):
            """Format disk metrics by device"""
            devices = {}
            for row in rows:
                device = row[1]
                if device not in devices:
                    devices[device] = {
                        'usage_avg': [],
                        'usage_max': [],
                        'free_avg': []
                    }
                devices[device]['usage_avg'].append(float(row[2]) if row[2] is not None else 0.0)
                devices[device]['usage_max'].append(float(row[3]) if row[3] is not None else 0.0)
                devices[device]['free_avg'].append(float(row[4]) if row[4] is not None else 0.0)
            return devices

        def _format_network_metrics(self, rows):
            """Format network metrics by interface"""
            interfaces = {}
            for row in rows:
                interface = row[1]
                if interface not in interfaces:
                    interfaces[interface] = {
                        'bytes_sent': [],
                        'bytes_recv': [],
                        'errors': []
                    }
                interfaces[interface]['bytes_sent'].append(float(row[2]) if row[2] is not None else 0.0)
                interfaces[interface]['bytes_recv'].append(float(row[3]) if row[3] is not None else 0.0)
                interfaces[interface]['errors'].append(int(row[4]) if row[4] is not None else 0)
            return interfaces

        def _calculate_summary(self, metrics):
            """Calculate summary statistics for historical metrics"""
            if not metrics['timestamps']:
                return {'error': 'No data available'}

            return {
                'cpu': {
                    'average': round(sum(metrics['cpu']['average']) / len(metrics['cpu']['average']), 2),
                    'max': round(max(metrics['cpu']['max']), 2),
                    'peak_load': {
                        '1m': round(max(metrics['cpu']['load_averages']['1m']), 2),
                        '5m': round(max(metrics['cpu']['load_averages']['5m']), 2),
                        '15m': round(max(metrics['cpu']['load_averages']['15m']), 2)
                    }
                },
                'memory': {
                    'average_usage': round(sum(metrics['memory']['average']) / len(metrics['memory']['average']), 2),
                    'peak_usage': round(max(metrics['memory']['max']), 2),
                    'peak_swap': round(max(metrics['memory']['swap']), 2)
                },
                'disks': {
                    device: {
                        'avg_usage': round(sum(data['usage_avg']) / len(data['usage_avg']), 2),
                        'peak_usage': round(max(data['usage_max']), 2),
                        'min_free': round(min(data['free_avg']), 2)
                    } for device, data in metrics['disks'].items()
                },
                'network': {
                    interface: {
                        'total_sent_gb': round(sum(data['bytes_sent']) / (1024 * 1024 * 1024), 2),
                        'total_recv_gb': round(sum(data['bytes_recv']) / (1024 * 1024 * 1024), 2),
                        'total_errors': sum(data['errors'])
                    } for interface, data in metrics['network'].items()
                }
            }

    @namespace.route('/alerts')
    class HostAlerts(Resource):
        """Endpoint for host system alerts and thresholds"""
        
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.host_monitor = services['host_monitor']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: 'Success',
                500: 'Internal server error'
            }
        )
        def get(self):
            """Get current system alerts based on thresholds"""
            try:
                metrics = self.host_monitor.get_all_metrics()
                alerts = []

                # Check CPU usage
                if metrics['cpu']['percent'] > 90:
                    alerts.append({
                        'level': 'critical',
                        'component': 'cpu',
                        'message': f"High CPU usage: {metrics['cpu']['percent']}%"
                    })
                elif metrics['cpu']['percent'] > 75:
                    alerts.append({
                        'level': 'warning',
                        'component': 'cpu',
                        'message': f"Elevated CPU usage: {metrics['cpu']['percent']}%"
                    })

                # Check memory usage
                if metrics['memory']['percent_used'] > 90:
                    alerts.append({
                        'level': 'critical',
                        'component': 'memory',
                        'message': f"High memory usage: {metrics['memory']['percent_used']}%"
                    })
                elif metrics['memory']['percent_used'] > 80:
                    alerts.append({
                        'level': 'warning',
                        'component': 'memory',
                        'message': f"Elevated memory usage: {metrics['memory']['percent_used']}%"
                    })

                # Check disk usage
                for disk in metrics['disks']:
                    if disk['percent_used'] > 90:
                        alerts.append({
                            'level': 'critical',
                            'component': 'disk',
                            'message': f"High disk usage on {disk['mount_point']}: {disk['percent_used']}%"
                        })
                    elif disk['percent_used'] > 80:
                        alerts.append({
                            'level': 'warning',
                            'component': 'disk',
                            'message': f"Elevated disk usage on {disk['mount_point']}: {disk['percent_used']}%"
                        })

                return {
                    'timestamp': datetime.now().isoformat(),
                    'alert_count': len(alerts),
                    'alerts': alerts
                }

            except Exception as e:
                self.logger.error(f"Error getting system alerts: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")
    @namespace.route('/details')
    class HostDetails(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.host_monitor = services['host_monitor']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: 'Success',
                500: 'Internal server error'
            }
        )
        @namespace.marshal_with(namespace.models['host_info'])
        def get(self):
            """Get detailed host system information"""
            try:
                return self.host_monitor.get_host_details()
            except Exception as e:
                self.logger.error(f"Error getting host details: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")

    return None              
