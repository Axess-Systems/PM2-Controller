# core/database.py

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

    # Commit changes
    conn.commit()