# core/database.py

import sqlite3
import threading
import logging
from typing import Callable

class DatabaseConnection:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(self.db_path)
        return self._local.connection

    def close_all(self):
        """Close all database connections"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            del self._local.connection

def setup_database(config, logger) -> None:
    """Initialize database"""
    conn = None
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()

        # Create host metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS host_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cpu_percent REAL,
                cpu_count INTEGER,
                load_avg_1m REAL,
                load_avg_5m REAL,
                load_avg_15m REAL,
                memory_total REAL,
                memory_used REAL,
                memory_percent REAL,
                swap_total REAL,
                swap_used REAL,
                swap_percent REAL
            )
        ''')

        # Create disk metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS disk_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device TEXT NOT NULL,
                total REAL,
                used REAL,
                free REAL,
                percent_used REAL,
                mount_point TEXT,
                UNIQUE(timestamp, device)
            )
        ''')

        # Create network metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS network_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                interface TEXT NOT NULL,
                bytes_sent REAL,
                bytes_recv REAL,
                packets_sent INTEGER,
                packets_recv INTEGER,
                errors_in INTEGER,
                errors_out INTEGER,
                UNIQUE(timestamp, interface)
            )
        ''')

        # Create service status table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS service_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT,
                timestamp TEXT,
                status INTEGER,
                cpu_usage REAL,
                memory_usage REAL,
                has_error BOOLEAN DEFAULT 0,
                has_warning BOOLEAN DEFAULT 0
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_host_metrics_timestamp ON host_metrics(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_disk_metrics_timestamp ON disk_metrics(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_network_metrics_timestamp ON network_metrics(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_service_status_timestamp ON service_status(timestamp)')

        # Create cleanup triggers
        retention_days = getattr(config, 'MONITORING_RETENTION_DAYS', 30)
        
        tables = ['host_metrics', 'disk_metrics', 'network_metrics', 'service_status']
        for table in tables:
            cursor.execute(f'''
                CREATE TRIGGER IF NOT EXISTS cleanup_old_{table}
                AFTER INSERT ON {table}
                BEGIN
                    DELETE FROM {table} 
                    WHERE timestamp <= datetime('now', '-{retention_days} days');
                END
            ''')

        conn.commit()
        logger.info("Database setup completed successfully")
        
        return DatabaseConnection(config.DB_PATH).get_connection

    except Exception as e:
        logger.error(f"Database setup failed: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()