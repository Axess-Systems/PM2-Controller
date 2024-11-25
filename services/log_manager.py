# services/log_manager.py

import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque
from core.config import Config
from core.exceptions import ProcessNotFoundError
from services.pm2 import PM2Service

class LogManager:
    """Enhanced service for managing PM2 process logs"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
    
    def _read_log_file(self, file_path: Path, num_lines: int) -> List[str]:
        """Read the last N lines from a log file"""
        try:
            if not file_path or not Path(file_path).exists():
                return [f"Log file not found: {file_path}"]
                
            with open(file_path, 'r') as f:
                return list(deque(f, num_lines))
        except Exception as e:
            self.logger.error(f"Error reading log file {file_path}: {str(e)}")
            return [f"Error reading log: {str(e)}"]
    
    def get_process_logs_by_type(self, process_name: str, log_type: str, 
                                num_lines: int, log_paths: Dict[str, str]) -> Dict:
        """Get logs for a specific process and type
        
        Args:
            process_name: Name of the process
            log_type: Type of log to retrieve ('error' or 'out')
            num_lines: Number of lines to return
            log_paths: Dictionary containing log file paths
            
        Returns:
            Dict containing logs and file information
        """
        try:
            # Get the appropriate log path
            log_path = Path(log_paths.get(log_type, ''))
            
            if not log_path or not log_path.exists():
                return {
                    'logs': [f"Log file not found: {log_type}"],
                    'files': {
                        'path': str(log_path) if log_path else None,
                        'size': 0,
                        'exists': False
                    }
                }
            
            # Read logs
            logs = self._read_log_file(log_path, num_lines)
            
            # Get file information
            file_stats = log_path.stat()
            
            return {
                'logs': logs,
                'files': {
                    'path': str(log_path),
                    'size': file_stats.st_size,
                    'exists': True,
                    'modified': file_stats.st_mtime
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting {log_type} logs for {process_name}: {str(e)}")
            raise
    
    def clear_process_logs(self, process_name: str) -> Dict:
        """Clear logs for a specific process"""
        try:
            # Get process information
            process = self.pm2_service.get_process(process_name)
            
            # Get log paths from PM2 environment
            pm2_env = process.get('pm2_env', {})
            log_paths = {
                'out': Path(pm2_env.get('pm_out_log_path', '')),
                'error': Path(pm2_env.get('pm_err_log_path', ''))
            }
            
            cleared_files = {}
            
            # Clear each log file
            for log_type, path in log_paths.items():
                if path and path.exists():
                    path.write_text('')
                    cleared_files[log_type] = {
                        'path': str(path),
                        'cleared': True
                    }
                else:
                    cleared_files[log_type] = {
                        'path': str(path) if path else None,
                        'cleared': False,
                        'reason': 'File not found'
                    }
            
            return {
                'message': f"Logs cleared for process {process_name}",
                'files': cleared_files
            }
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Error clearing logs for {process_name}: {str(e)}")
            raise