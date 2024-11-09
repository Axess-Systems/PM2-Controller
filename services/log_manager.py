import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque
from core.config import Config
from core.exceptions import ProcessNotFoundError
from services.pm2 import PM2Service

class LogManager:
    """Service for managing PM2 process logs"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
    
    def _read_log_file(self, file_path: Path, num_lines: int) -> List[str]:
        """Read the last N lines from a log file"""
        try:
            if not file_path.exists():
                return [f"Log file not found: {file_path}"]
                
            with open(file_path, 'r') as f:
                return list(deque(f, num_lines))
        except Exception as e:
            self.logger.error(f"Error reading log file {file_path}: {str(e)}")
            return [f"Error reading log: {str(e)}"]
    
    def get_process_logs(self, process_name: str, num_lines: Optional[int] = None) -> Dict:
        """Get logs for a specific process"""
        try:
            # Get process information
            process = self.pm2_service.get_process(process_name)
            
            # Get log paths from PM2 environment
            out_log_path = Path(process['pm2_env'].get('pm_out_log_path', ''))
            err_log_path = Path(process['pm2_env'].get('pm_err_log_path', ''))
            
            # Limit number of lines
            if num_lines is None:
                num_lines = self.config.MAX_LOG_LINES
            else:
                num_lines = min(num_lines, self.config.MAX_LOG_LINES)
            
            # Read logs
            out_logs = self._read_log_file(out_log_path, num_lines)
            err_logs = self._read_log_file(err_log_path, num_lines)
            
            # Combine and format logs
            logs = []
            logs.extend([f"[OUT] {line.rstrip()}" for line in out_logs])
            logs.extend([f"[ERR] {line.rstrip()}" for line in err_logs])
            
            return {
                'logs': logs,
                'files': {
                    'out': str(out_log_path),
                    'err': str(err_log_path),
                    'out_size': out_log_path.stat().st_size if out_log_path.exists() else 0,
                    'err_size': err_log_path.stat().st_size if err_log_path.exists() else 0
                }
            }
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting logs for process {process_name}: {str(e)}")
            raise
    
    def clear_process_logs(self, process_name: str) -> Dict:
        """Clear logs for a specific process"""
        try:
            # Get process information
            process = self.pm2_service.get_process(process_name)
            
            # Get log paths from PM2 environment
            out_log_path = Path(process['pm2_env'].get('pm_out_log_path', ''))
            err_log_path = Path(process['pm2_env'].get('pm_err_log_path', ''))
            
            # Clear log files
            if out_log_path.exists():
                out_log_path.write_text('')
            if err_log_path.exists():
                err_log_path.write_text('')
            
            return {
                "message": f"Logs cleared for process {process_name}",
                "files": {
                    "out": str(out_log_path),
                    "err": str(err_log_path)
                }
            }
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Error clearing logs for process {process_name}: {str(e)}")
            raise