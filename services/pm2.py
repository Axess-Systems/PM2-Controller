import subprocess
import json
import time
from typing import Union, Dict, List
import logging
from ..core.config import Config
from ..core.exceptions import (
    PM2Error, ProcessNotFoundError, PM2TimeoutError,
    PM2CommandError, parse_pm2_error
)

class PM2Service:
    """Service for interacting with PM2 process manager"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def execute_command(self, command: str, retry: bool = True) -> Union[str, Dict]:
        """
        Execute a PM2 command with enhanced error handling and retry logic
        
        Args:
            command: PM2 command to execute
            retry: Whether to retry on failure
            
        Returns:
            Command output as string or parsed JSON
            
        Raises:
            ProcessNotFoundError: When process is not found
            ProcessAlreadyExistsError: When process already exists
            PM2CommandError: For other PM2 related errors
            PM2TimeoutError: When command times out
        """
        retries = self.config.MAX_RETRIES if retry else 1
        last_error = None
        
        for attempt in range(retries):
            try:
                result = subprocess.run(
                    f"{self.config.PM2_BIN} {command}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.config.COMMAND_TIMEOUT
                )
                
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, 
                        command, 
                        result.stdout, 
                        result.stderr
                    )
                
                if 'jlist' in command:
                    try:
                        return json.loads(result.stdout)
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Failed to parse PM2 JSON output: {str(e)}")
                        raise PM2CommandError(f"Invalid JSON output from PM2: {str(e)}")
                return result.stdout
                
            except subprocess.TimeoutExpired as e:
                last_error = PM2TimeoutError(f"Command timed out after {self.config.COMMAND_TIMEOUT} seconds")
                self.logger.error(f"PM2 command timeout (attempt {attempt + 1}/{retries}): {str(e)}")
                
            except subprocess.CalledProcessError as e:
                last_error = parse_pm2_error(e.stderr.strip())
                self.logger.error(f"PM2 command failed (attempt {attempt + 1}/{retries}): {e.stderr}")
                
            except Exception as e:
                last_error = PM2CommandError(f"Failed to execute PM2 command: {str(e)}")
                self.logger.error(f"Unexpected error (attempt {attempt + 1}/{retries}): {str(e)}")
            
            if attempt < retries - 1:
                time.sleep(self.config.RETRY_DELAY)
        
        raise last_error
    
    def list_processes(self) -> List[Dict]:
        """Get list of all PM2 processes"""
        return self.execute_command("jlist")
    
    def get_process(self, name: str) -> Dict:
        """Get details of a specific process"""
        processes = self.list_processes()
        process = next((p for p in processes if p['name'] == name), None)
        
        if not process:
            raise ProcessNotFoundError(f"Process {name} not found")
        
        return process
    
    def start_process(self, name: str) -> str:
        """Start a specific process"""
        process = self.get_process(name)
        return self.execute_command(f"start {process['pm_id']}")
    
    def stop_process(self, name: str) -> str:
        """Stop a specific process"""
        process = self.get_process(name)
        return self.execute_command(f"stop {process['pm_id']}")
    
    def restart_process(self, name: str) -> str:
        """Restart a specific process"""
        process = self.get_process(name)
        return self.execute_command(f"restart {process['pm_id']}")
    
    def delete_process(self, name: str) -> str:
        """Delete a specific process"""
        return self.execute_command(f"delete {name}")
    
    def reload_process(self, name: str) -> str:
        """Reload a specific process (zero-downtime restart)"""
        return self.execute_command(f"reload {name}")