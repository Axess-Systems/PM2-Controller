# api/routes/monitoring.py

from datetime import datetime, timedelta
from flask import request
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError
import sqlite3
from typing import Dict, List

def create_monitoring_routes(namespace, services):
    """Create routes for process monitoring"""
    
    @namespace.route('/processes/<string:process_name>/monitoring')
    class ProcessMonitoring(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

        @namespace.doc(
            params={
                'timeframe': {'description': 'Monitoring timeframe in minutes', 'type': 'integer', 'default': 60},
                'interval': {'description': 'Data point interval in seconds', 'type': 'integer', 'default': 60}
            },
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        @namespace.marshal_with(namespace.models['metrics'])
        def get(self, process_name):
            """Get process monitoring metrics"""
            try:
                # Get query parameters with defaults
                timeframe = int(request.args.get('timeframe', 60))
                interval = int(request.args.get('interval', 60))
                
                # Calculate time range
                end_time = datetime.now()
                start_time = end_time - timedelta(minutes=timeframe)

                # Get process metrics from database
                metrics = self.get_process_metrics(
                    process_name, 
                    start_time, 
                    end_time, 
                    interval
                )

                # Calculate summary statistics
                summary = self.calculate_metrics_summary(metrics)

                return {
                    'process_name': process_name,
                    'time_range': f'Last {timeframe} minutes',
                    'metrics': metrics,
                    'summary': summary
                }

            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except Exception as e:
                self.logger.error(f"Error getting metrics for {process_name}: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")



    def get_process_metrics(self, process_name: str, time_range: int = 72) -> List[Dict]:
        """Get process metrics with proper time intervals
        
        Args:
            process_name: Name of the process
            time_range: Hours of data to retrieve (default: 72)
        """
        conn = None
        try:
            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=time_range)

            # Query with proper time intervals
            cursor.execute('''
                WITH RECURSIVE 
                TimePoints(time_point) AS (
                    -- Generate time points at 1-minute intervals
                    SELECT datetime(?, 'localtime')
                    UNION ALL
                    SELECT datetime(time_point, '+1 minute')
                    FROM TimePoints
                    WHERE time_point < datetime(?, 'localtime')
                ),
                ProcessMetrics AS (
                    -- Get actual metrics data
                    SELECT 
                        strftime('%Y-%m-%dT%H:%M:00', timestamp) as metric_time,
                        AVG(cpu_usage) as cpu,
                        MAX(status) as status,
                        MAX(has_error) as has_error
                    FROM service_status
                    WHERE service_name = ?
                    AND timestamp BETWEEN datetime(?, 'localtime') AND datetime(?, 'localtime')
                    GROUP BY metric_time
                )
                SELECT 
                    TimePoints.time_point as timestamp,
                    COALESCE(ProcessMetrics.cpu, 0) as value,
                    CASE
                        WHEN ProcessMetrics.has_error = 1 THEN 'red'
                        WHEN ProcessMetrics.status = 0 THEN 'gray'
                        WHEN ProcessMetrics.cpu > 90 THEN 'red'
                        WHEN ProcessMetrics.cpu > 75 THEN 'orange'
                        ELSE 'green'
                    END as status
                FROM TimePoints
                LEFT JOIN ProcessMetrics ON TimePoints.time_point = ProcessMetrics.metric_time
                ORDER BY TimePoints.time_point
            ''', (
                start_time.strftime('%Y-%m-%d %H:%M:%S'),
                end_time.strftime('%Y-%m-%d %H:%M:%S'),
                process_name,
                start_time.strftime('%Y-%m-%d %H:%M:%S'),
                end_time.strftime('%Y-%m-%d %H:%M:%S')
            ))

            rows = cursor.fetchall()
            
            # Format the response
            metrics = [
                {
                    'timestamp': row[0],
                    'value': float(row[1]) if row[1] is not None else 0.0,
                    'status': row[2]
                }
                for row in rows
            ]

            return {
                'process_name': process_name,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'interval': '1 minute',
                'data': metrics
            }

        except Exception as e:
            self.logger.error(f"Error getting metrics for {process_name}: {str(e)}")
            raise
        finally:
            if conn:
                conn.close()


        def calculate_metrics_summary(self, metrics):
            """Calculate summary statistics for metrics"""
            if not metrics['cpu'] or not metrics['memory']:
                return {
                    'error': 'No metrics data available'
                }

            return {
                'cpu': {
                    'avg': sum(metrics['cpu']) / len(metrics['cpu']),
                    'max': max(metrics['cpu']),
                    'min': min(metrics['cpu'])
                },
                'memory': {
                    'avg': sum(metrics['memory']) / len(metrics['memory']),
                    'max': max(metrics['memory']),
                    'min': min(metrics['memory'])
                },
                'errors': sum(metrics['errors']),
                'warnings': sum(metrics['warnings']),
                'status_distribution': {
                    status: metrics['status'].count(status)
                    for status in set(metrics['status'])
                }
            }

    @namespace.route('/processes/<string:process_name>/status')
    class ProcessStatus(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        @namespace.marshal_with(namespace.models['status'])
        def get(self, process_name):
            """Get current process status"""
            try:
                # Get process info from PM2
                process = self.pm2_service.get_process(process_name)
                
                # Get recent errors from database
                recent_errors = self.get_recent_errors(process_name)
                
                # Format response
                monit_data = process.get('monit', {})
                pm2_env = process.get('pm2_env', {})
                
                return {
                    'pid': process.get('pid'),
                    'name': process_name,
                    'pm_id': process.get('pm_id'),
                    'monit': {
                        'memory': monit_data.get('memory', 0),
                        'cpu': monit_data.get('cpu', 0),
                        'timestamp': datetime.now()
                    },
                    'status': pm2_env.get('status', 'unknown'),
                    'uptime': pm2_env.get('pm_uptime', 0),
                    'restart_time': pm2_env.get('restart_time', 0),
                    'unstable_restarts': pm2_env.get('unstable_restarts', 0),
                    'created_at': datetime.fromtimestamp(pm2_env.get('created_at', 0)),
                    'errors': recent_errors
                }

            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except Exception as e:
                self.logger.error(f"Error getting status for {process_name}: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")

        def get_recent_errors(self, process_name, hours=24):
            """Get recent errors from database"""
            conn = sqlite3.connect(Config.DB_PATH)
            try:
                cursor = conn.cursor()
                start_time = datetime.now() - timedelta(hours=hours)
                
                cursor.execute('''
                    SELECT timestamp, status, has_error, has_warning
                    FROM service_status 
                    WHERE service_name = ? 
                    AND timestamp >= ?
                    AND (has_error = 1 OR has_warning = 1)
                    ORDER BY timestamp DESC
                ''', (
                    process_name,
                    start_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                rows = cursor.fetchall()
                
                return [{
                    'timestamp': datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'),
                    'type': 'error' if row[2] else 'warning',
                    'details': {
                        'status_code': row[1],
                        'is_error': bool(row[2]),
                        'is_warning': bool(row[3])
                    }
                } for row in rows]
                
            finally:
                conn.close()

    @namespace.route('/processes/<string:process_name>/heatmap')
    class ProcessHeatmap(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']
            self.config = services['config']

        @namespace.doc(
            params={
                'metric': {'description': 'Metric to visualize (cpu/memory)', 'enum': ['cpu', 'memory']},
                'period': {'description': 'Time period in hours', 'type': 'integer', 'default': 72},
                'interval': {'description': 'Aggregation interval in minutes', 'type': 'integer', 'default': 15}
            },
            responses={
                200: 'Success',
                404: 'Process not found',
                400: 'Invalid parameters',
                500: 'Internal server error'
            }
        )
        @namespace.marshal_with(namespace.models['heatmap'])
        def get(self, process_name):
            """Get process metric heatmap data"""
            try:
                metric = request.args.get('metric', 'cpu')
                period = int(request.args.get('period', 72))
                interval = int(request.args.get('interval', 15))

                if metric not in ['cpu', 'memory']:
                    raise ValueError("Invalid metric type")

                # Define thresholds for colors
                thresholds = self._get_metric_thresholds(metric)
                
                # Get heatmap data
                data = self._get_heatmap_data(
                    process_name, 
                    metric, 
                    period, 
                    interval,
                    thresholds
                )

                return {
                    'process_name': process_name,
                    'metric_type': metric,
                    'time_range': f'Last {period} hours',
                    'interval': f'{interval} minutes',
                    'thresholds': thresholds,
                    'data': data
                }

            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except ValueError as e:
                namespace.abort(400, str(e))
            except Exception as e:
                self.logger.error(f"Error getting heatmap for {process_name}: {str(e)}")
                namespace.abort(500, str(e))

        def _get_metric_thresholds(self, metric):
            """Get thresholds for metric coloring"""
            if metric == 'cpu':
                return {
                    'low': {'max': 30, 'color': 'green'},
                    'medium': {'max': 70, 'color': 'yellow'},
                    'high': {'max': 90, 'color': 'orange'},
                    'critical': {'color': 'red'}
                }
            else:  # memory
                return {
                    'low': {'max': 256, 'color': 'green'},  # MB
                    'medium': {'max': 512, 'color': 'yellow'},
                    'high': {'max': 1024, 'color': 'orange'},
                    'critical': {'color': 'red'}
                }

        def _get_heatmap_data(self, process_name, metric, period, interval, thresholds):
            """Get aggregated data for heatmap"""
            conn = sqlite3.connect(self.config.DB_PATH)
            try:
                cursor = conn.cursor()
                end_time = datetime.now()
                start_time = end_time - timedelta(hours=period)
                
                # Query with proper aggregation
                cursor.execute(f'''
                    WITH intervals AS (
                        SELECT 
                            strftime('%Y-%m-%d %H:%M:00', timestamp) as interval_start,
                            AVG({"cpu_usage" if metric == "cpu" else "memory_usage"}) as avg_value,
                            MAX(has_error) as had_error,
                            MAX(has_warning) as had_warning
                        FROM service_status 
                        WHERE service_name = ? 
                        AND timestamp BETWEEN ? AND ?
                        GROUP BY interval_start
                        ORDER BY interval_start ASC
                    )
                    SELECT * FROM intervals
                ''', (
                    process_name,
                    start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                rows = cursor.fetchall()
                
                return [{
                    'timestamp': datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'),
                    'value': float(row[1]) if row[1] is not None else 0.0,
                    'status': self._get_value_color(float(row[1]) if row[1] is not None else 0.0, thresholds),
                    'had_error': bool(row[2]),
                    'had_warning': bool(row[3])
                } for row in rows]
                
            finally:
                conn.close()

        def _get_value_color(self, value, thresholds):
            """Determine color based on value and thresholds"""
            if value <= thresholds['low']['max']:
                return thresholds['low']['color']
            elif value <= thresholds['medium']['max']:
                return thresholds['medium']['color']
            elif value <= thresholds['high']['max']:
                return thresholds['high']['color']
            return thresholds['critical']['color']

    @namespace.route('/processes/<string:process_name>/historical')
    class ProcessHistorical(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']
            self.config = services['config']

        @namespace.doc(
            params={
                'start': {'description': 'Start timestamp (ISO format)', 'type': 'string'},
                'end': {'description': 'End timestamp (ISO format)', 'type': 'string'},
                'interval': {'description': 'Aggregation interval in minutes', 'type': 'integer', 'default': 60}
            }
        )
        @namespace.marshal_with(namespace.models['historical'])
        def get(self, process_name):
            """Get historical metrics for specific time range"""
            try:
                # Parse time range
                end_time = datetime.fromisoformat(request.args.get('end', datetime.now().isoformat()))
                start_time = datetime.fromisoformat(request.args.get('start', (end_time - timedelta(days=7)).isoformat()))
                interval = int(request.args.get('interval', 60))

                # Get historical data
                metrics_data = self._get_historical_data(process_name, start_time, end_time, interval)
                
                # Calculate statistics
                statistics = self._calculate_statistics(metrics_data)

                return {
                    'process_name': process_name,
                    'start_time': start_time,
                    'end_time': end_time,
                    'interval': f'{interval} minutes',
                    'metrics': metrics_data,
                    'statistics': statistics
                }

            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except ValueError as e:
                namespace.abort(400, str(e))
            except Exception as e:
                self.logger.error(f"Error getting historical data for {process_name}: {str(e)}")
                namespace.abort(500, str(e))

        def _get_historical_data(self, process_name, start_time, end_time, interval):
            """Get historical metrics with aggregation"""
            conn = sqlite3.connect(self.config.DB_PATH)
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    WITH intervals AS (
                        SELECT 
                            strftime('%Y-%m-%d %H:%M:00', timestamp) as interval_start,
                            AVG(cpu_usage) as avg_cpu,
                            MAX(cpu_usage) as max_cpu,
                            MIN(cpu_usage) as min_cpu,
                            AVG(memory_usage) as avg_memory,
                            MAX(memory_usage) as max_memory,
                            MIN(memory_usage) as min_memory,
                            COUNT(CASE WHEN has_error = 1 THEN 1 END) as error_count,
                            COUNT(CASE WHEN has_warning = 1 THEN 1 END) as warning_count
                        FROM service_status 
                        WHERE service_name = ? 
                        AND timestamp BETWEEN ? AND ?
                        GROUP BY interval_start
                        ORDER BY interval_start ASC
                    )
                    SELECT * FROM intervals
                ''', (
                    process_name,
                    start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    end_time.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                rows = cursor.fetchall()
                
                return {
                    'timestamps': [row[0] for row in rows],
                    'cpu': {
                        'avg': [float(row[1]) if row[1] is not None else 0.0 for row in rows],
                        'max': [float(row[2]) if row[2] is not None else 0.0 for row in rows],
                        'min': [float(row[3]) if row[3] is not None else 0.0 for row in rows]
                    },
                    'memory': {
                        'avg': [float(row[4]) if row[4] is not None else 0.0 for row in rows],
                        'max': [float(row[5]) if row[5] is not None else 0.0 for row in rows],
                        'min': [float(row[6]) if row[6] is not None else 0.0 for row in rows]
                    },
                    'errors': [int(row[7]) for row in rows],
                    'warnings': [int(row[8]) for row in rows]
                }
                
            finally:
                conn.close()

        def _calculate_statistics(self, data):
            """Calculate statistical summary of historical data"""
            if not data['timestamps']:
                return {'error': 'No data available'}

            def calc_stats(values):
                return {
                    'avg': round(sum(values) / len(values), 2),
                    'max': round(max(values), 2),
                    'min': round(min(values), 2),
                    'total_points': len(values)
                }

            return {
                'cpu': {
                    'average': calc_stats(data['cpu']['avg']),
                    'maximum': calc_stats(data['cpu']['max']),
                    'minimum': calc_stats(data['cpu']['min'])
                },
                'memory': {
                    'average': calc_stats(data['memory']['avg']),
                    'maximum': calc_stats(data['memory']['max']),
                    'minimum': calc_stats(data['memory']['min'])
                },
                'incidents': {
                    'total_errors': sum(data['errors']),
                    'total_warnings': sum(data['warnings'])
                }
            }

    return None
