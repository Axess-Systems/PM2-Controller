# api/models/host.py

from flask_restx import fields

def create_host_models(api):
    """Create models for host system monitoring"""
    
    # Process monitoring stats model
    monit_model = api.model('ProcessMonitoring', {
        'memory': fields.Integer(description='Memory usage in bytes'),
        'cpu': fields.Float(description='CPU usage percentage'),
        'timestamp': fields.DateTime(description='Monitoring timestamp')
    })

    # CPU details model
    cpu_info_model = api.model('CPUInfo', {
        'cores_physical': fields.Integer(description='Number of physical CPU cores'),
        'cores_logical': fields.Integer(description='Number of logical CPU cores'),
        'usage_percent': fields.Float(description='Current CPU usage percentage'),
        'per_cpu_percent': fields.List(fields.Float, description='Per CPU core usage percentage'),
        'load_avg_1m': fields.Float(description='1 minute load average'),
        'load_avg_5m': fields.Float(description='5 minute load average'),
        'load_avg_15m': fields.Float(description='15 minute load average'),
        'frequency_current': fields.Float(description='Current CPU frequency in MHz'),
        'frequency_min': fields.Float(description='Minimum CPU frequency in MHz'),
        'frequency_max': fields.Float(description='Maximum CPU frequency in MHz')
    })

    # Memory details model
    memory_info_model = api.model('MemoryInfo', {
        'total': fields.Float(description='Total physical memory in GB'),
        'available': fields.Float(description='Available memory in GB'),
        'used': fields.Float(description='Used memory in GB'),
        'free': fields.Float(description='Free memory in GB'),
        'percent_used': fields.Float(description='Percentage of memory used'),
        'swap_total': fields.Float(description='Total swap memory in GB'),
        'swap_used': fields.Float(description='Used swap memory in GB'),
        'swap_free': fields.Float(description='Free swap memory in GB'),
        'swap_percent': fields.Float(description='Percentage of swap used')
    })

    # Disk details model
    disk_info_model = api.model('DiskInfo', {
        'device': fields.String(description='Device name'),
        'mount_point': fields.String(description='Mount point'),
        'fs_type': fields.String(description='Filesystem type'),
        'total_size': fields.Float(description='Total size in GB'),
        'used': fields.Float(description='Used space in GB'),
        'free': fields.Float(description='Free space in GB'),
        'percent_used': fields.Float(description='Percentage of disk used')
    })

    # Network interface model
    network_interface_model = api.model('NetworkInterface', {
        'name': fields.String(description='Interface name'),
        'ip_address': fields.String(description='IP address'),
        'mac_address': fields.String(description='MAC address'),
        'netmask': fields.String(description='Network mask'),
        'bytes_sent': fields.Float(description='Total bytes sent'),
        'bytes_recv': fields.Float(description='Total bytes received'),
        'packets_sent': fields.Integer(description='Packets sent'),
        'packets_recv': fields.Integer(description='Packets received'),
        'errors_in': fields.Integer(description='Input errors'),
        'errors_out': fields.Integer(description='Output errors'),
        'speed': fields.Float(description='Interface speed in Mbps', required=False)
    })

    # Complete host info model
    host_info_model = api.model('HostInfo', {
        'timestamp': fields.DateTime(description='Time of data collection'),
        'hostname': fields.String(description='System hostname'),
        'os': fields.String(description='Operating system name and version'),
        'kernel': fields.String(description='Kernel version'),
        'arch': fields.String(description='System architecture'),
        'uptime': fields.Float(description='System uptime in seconds'),
        'boot_time': fields.DateTime(description='System boot time'),
        'cpu': fields.Nested(cpu_info_model),
        'memory': fields.Nested(memory_info_model),
        'disks': fields.List(fields.Nested(disk_info_model)),
        'networks': fields.List(fields.Nested(network_interface_model)),
        'process_count': fields.Integer(description='Total number of processes'),
        'users_count': fields.Integer(description='Number of logged in users')
    })

    # Historical metrics model
    historical_metrics_model = api.model('HistoricalMetrics', {
        'start_time': fields.DateTime(description='Start of time range'),
        'end_time': fields.DateTime(description='End of time range'),
        'interval': fields.String(description='Data aggregation interval'),
        'metrics': fields.Raw(description='Time series metrics data'),
        'summary': fields.Raw(description='Statistical summary')
    })

    # Host metrics model (for periodic monitoring)
    host_metrics_model = api.model('HostMetrics', {
        'timestamp': fields.DateTime(description='Metrics timestamp'),
        'cpu_percent': fields.Float(description='CPU usage percentage'),
        'memory_percent': fields.Float(description='Memory usage percentage'),
        'disk_usage': fields.Raw(description='Disk usage by mount point'),
        'network_io': fields.Raw(description='Network IO statistics'),
        'load_average': fields.List(fields.Float, description='System load averages [1m, 5m, 15m]')
    })

    # System alerts model
    alert_model = api.model('SystemAlert', {
        'timestamp': fields.DateTime(description='Alert timestamp'),
        'level': fields.String(description='Alert level (warning/critical)', enum=['warning', 'critical']),
        'component': fields.String(description='System component (cpu/memory/disk/network)'),
        'message': fields.String(description='Alert message'),
        'value': fields.Float(description='Current value that triggered the alert'),
        'threshold': fields.Float(description='Threshold value that was exceeded')
    })

    return {
        'monit': monit_model,
        'cpu_info': cpu_info_model,
        'memory_info': memory_info_model,
        'disk_info': disk_info_model,
        'network_interface': network_interface_model,
        'host_info': host_info_model,
        'historical_metrics': historical_metrics_model,
        'host_metrics': host_metrics_model,
        'system_alert': alert_model
    }