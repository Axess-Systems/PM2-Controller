# core/database.py

import sqlite3
import threading
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

def setup_database(config) -> Callable:
    """Initialize database and return connection factory"""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        setup_tables(conn)
        return DatabaseConnection(config.DB_PATH).get_connection
    finally:
        conn.close()

def setup_tables(conn: sqlite3.Connection):
    """Set up all database tables"""
    cursor = conn.cursor()
    
    # Create tables
    setup_process_monitoring_tables(conn, cursor)
    setup_host_monitoring_tables(conn, cursor)
    
    conn.commit()

def setup_process_monitoring_tables(conn, cursor):
    """Set up database tables for process monitoring"""
    
    # Service status table
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

    # Create index
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_service_status_timestamp 
        ON service_status(timestamp)
    ''')

    # Create cleanup trigger
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cleanup_old_service_status
        AFTER INSERT ON service_status
        BEGIN
            DELETE FROM service_status 
            WHERE timestamp <= datetime('now', '-30 days');
        END
    ''')

    conn.commit()

def setup_host_monitoring_tables(conn, cursor):
    """Set up database tables for host monitoring"""
    
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

    # Create indexes
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_host_metrics_timestamp 
        ON host_metrics(timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_disk_metrics_timestamp_device 
        ON disk_metrics(timestamp, device)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_network_metrics_timestamp_interface 
        ON network_metrics(timestamp, interface)
    ''')

    # Create cleanup triggers
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cleanup_old_host_metrics
        AFTER INSERT ON host_metrics
        BEGIN
            DELETE FROM host_metrics 
            WHERE timestamp <= datetime('now', '-30 days');
        END
    ''')

    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cleanup_old_disk_metrics
        AFTER INSERT ON disk_metrics
        BEGIN
            DELETE FROM disk_metrics 
            WHERE timestamp <= datetime('now', '-30 days');
        END
    ''')

    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS cleanup_old_network_metrics
        AFTER INSERT ON network_metrics
        BEGIN
            DELETE FROM network_metrics 
            WHERE timestamp <= datetime('now', '-30 days');
        END
    ''')

    conn.commit()