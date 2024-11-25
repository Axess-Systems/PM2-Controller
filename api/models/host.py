# api/models/host.py

from flask_restx import fields

def create_host_models(api):
    """Create models for host system monitoring"""
    
    # Disk usage model
    disk_info_model = api.model('DiskInfo', {
        'device': fields.String(description='Device name/mount point'),
        'total': fields.Float(description='Total space in GB'),
        'used': fields.Float(description='Used space in GB'),
        'free': fields.Float(description='Free space in GB'),
        'percent_used': fields.Float(description='Percentage used'),
        'mount_point': fields.String(description='Mount point')
    })

    # CPU info model
    cpu_info_model = api.model('CPUInfo', {
        'count': fields.Integer(description='Number of CPU cores'),
        'percent': fields.Float(description='Overall CPU usage percentage'),
        'per_cpu': fields.List(fields.Float, description='Per-CPU usage percentages'),
        'load_avg': fields.List(fields.Float, description='Load averages [1m, 5m, 15m]')
    })

    # Memory info model
    memory_info_model = api.model('MemoryInfo', {
        'total': fields.Float(description='Total RAM in GB'),
        'available': fields.Float(description='Available RAM in GB'),
        'used': fields.Float(description='Used RAM in GB'),
        'free': fields.Float(description='Free RAM in GB'),
        'percent_used': fields.Float(description='Percentage of RAM used'),
        'swap_total': fields.Float(description='Total swap in GB'),
        'swap_used': fields.Float(description='Used swap in GB'),
        'swap_percent': fields.Float(description='Percentage of swap used')
    })

    # Network info model
    network_stats_model = api.model('NetworkStats', {
        'interface': fields.String(description='Network interface name'),
        'bytes_sent': fields.Float(description='Total bytes sent'),
        'bytes_recv': fields.Float(description='Total bytes received'),
        'packets_sent': fields.Integer(description='Packets sent'),
        'packets_recv': fields.Integer(description='Packets received'),
        'errors_in': fields.Integer(description='Input errors'),
        'errors_out': fields.Integer(description='Output errors')
    })

    # Host info model
    host_info_model = api.model('HostInfo', {
        'hostname': fields.String(description='Server hostname'),
        'os': fields.String(description='Operating system'),
        'uptime': fields.Integer(description='System uptime in seconds'),
        'boot_time': fields.DateTime(description='System boot time')
    })

    # Complete host metrics model
    host_metrics_model = api.model('HostMetrics', {
        'timestamp': fields.DateTime(description='Metrics timestamp'),
        'host_info': fields.Nested(host_info_model),
        'cpu': fields.Nested(cpu_info_model),
        'memory': fields.Nested(memory_info_model),
        'disks': fields.List(fields.Nested(disk_info_model)),
        'network': fields.List(fields.Nested(network_stats_model))
    })

    # Historical host metrics model
    historical_host_metrics_model = api.model('HistoricalHostMetrics', {
        'start_time': fields.DateTime(description='Start of time range'),
        'end_time': fields.DateTime(description='End of time range'),
        'interval': fields.String(description='Data aggregation interval'),
        'metrics': fields.Raw(description='Time series metrics data'),
        'summary': fields.Raw(description='Statistical summary')
    })

    return {
        'disk_info': disk_info_model,
        'cpu_info': cpu_info_model,
        'memory_info': memory_info_model,
        'network_stats': network_stats_model,
        'host_info': host_info_model,
        'host_metrics': host_metrics_model,
        'historical_host': historical_host_metrics_model
    }