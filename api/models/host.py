# api/models/monitoring.py

from flask_restx import fields

def create_monitoring_models(api):
    """Create models for process monitoring endpoints with heatmap support"""
    
    # Base monitoring models (existing)
    monit_model = api.model('ProcessMonitoring', {
        'memory': fields.Integer(description='Memory usage in bytes'),
        'cpu': fields.Float(description='CPU usage percentage'),
        'timestamp': fields.DateTime(description='Monitoring timestamp')
    })

    error_model = api.model('ProcessError', {
        'timestamp': fields.DateTime(description='Error timestamp'),
        'type': fields.String(description='Error type', enum=['error', 'warning']),
        'details': fields.Raw(description='Error details')
    })

    # Heatmap data point model
    heatmap_point_model = api.model('HeatmapPoint', {
        'timestamp': fields.DateTime(description='Data point timestamp'),
        'value': fields.Float(description='Metric value'),
        'status': fields.String(description='Status color based on thresholds')
    })

    # Heatmap response model
    heatmap_model = api.model('Heatmap', {
        'process_name': fields.String(description='Process name'),
        'metric_type': fields.String(description='Type of metric (cpu/memory)'),
        'time_range': fields.String(description='Time range of data'),
        'interval': fields.String(description='Data aggregation interval'),
        'thresholds': fields.Raw(description='Color thresholds for values'),
        'data': fields.List(fields.Nested(heatmap_point_model))
    })

    # Historical metrics model
    historical_metrics_model = api.model('HistoricalMetrics', {
        'process_name': fields.String(description='Process name'),
        'start_time': fields.DateTime(description='Start of time range'),
        'end_time': fields.DateTime(description='End of time range'),
        'interval': fields.String(description='Data aggregation interval'),
        'metrics': fields.Raw(description='Time series metrics data'),
        'statistics': fields.Raw(description='Statistical summary')
    })

    # Add to existing models
    base_models = {
        'monit': monit_model,
        'error': error_model,
        'status': api.model('ProcessStatus', {
            'pid': fields.Integer(description='Process ID'),
            'name': fields.String(description='Process name'),
            'pm_id': fields.Integer(description='PM2 ID'),
            'monit': fields.Nested(monit_model),
            'status': fields.String(description='Process status'),
            'uptime': fields.Integer(description='Process uptime in seconds'),
            'restart_time': fields.Integer(description='Number of restarts'),
            'unstable_restarts': fields.Integer(description='Number of unstable restarts'),
            'created_at': fields.DateTime(description='Process creation timestamp'),
            'errors': fields.List(fields.Nested(error_model))
        }),
        'metrics': api.model('ProcessMetrics', {
            'process_name': fields.String(description='Process name'),
            'time_range': fields.String(description='Time range of metrics'),
            'metrics': fields.Raw(description='Process metrics data'),
            'summary': fields.Raw(description='Metrics summary')
        }),
        'heatmap': heatmap_model,
        'historical': historical_metrics_model
    }

    return base_models