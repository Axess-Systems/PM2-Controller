import subprocess
import json
import time
from typing import Union, Dict, List
import logging
from pathlib import Path
import re
import configparser
from core.config import Config
from core.exceptions import (
    PM2Error, ProcessNotFoundError, PM2TimeoutError,
    PM2CommandError, ProcessAlreadyExistsError,
    parse_pm2_error
)

class PM2Service:
    """Service for interacting with PM2 process manager"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def execute_command(self, command: str, retry: bool = True) -> Union[str, dict]:
        """Execute a PM2 command with enhanced error handling and retry logic"""
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
        processes = self.execute_command("jlist")
        
        # Add config file paths
        for process in processes:
            try:
                pm2_config = Path(f"/home/pm2/pm2-configs/{process['name']}.config.js")
                python_config = Path(f"/home/pm2/pm2-configs/{process['name']}.ini")
                
                process['config_files'] = {
                    'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                    'python_config': str(python_config) if python_config.exists() else None
                }
            except Exception as e:
                self.logger.warning(f"Error getting config paths for process {process['name']}: {str(e)}")
        
        return processes
    
    def get_process(self, name: str) -> Dict:
        """Get details of a specific process"""
        processes = self.list_processes()
        process = next((p for p in processes if p['name'] == name), None)
        
        if not process:
            raise ProcessNotFoundError(f"Process {name} not found")
        
        return process
    
    def get_process_config(self, name: str) -> Dict:
        """Get configuration files for a process"""
        try:
            # Get config file paths
            pm2_config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            python_config_path = Path(f"/home/pm2/pm2-configs/{name}.ini")

            # Check process exists
            if not any(p['name'] == name for p in self.list_processes()):
                raise ProcessNotFoundError(
                    f"Process {name} not found in PM2 process list. "
                    f"Checked config paths:\n"
                    f"PM2 Config: {pm2_config_path} (exists: {pm2_config_path.exists()})\n"
                    f"Python Config: {python_config_path} (exists: {python_config_path.exists()})"
                )

            configs = {}

            # Read PM2 config if exists
            if pm2_config_path.exists():
                with open(pm2_config_path, 'r') as f:
                    content = f.read()
                    match = re.search(r'apps:\s*\[\s*({[^}]+})', content, re.DOTALL)
                    if match:
                        config_str = match.group(1).replace("'", '"')
                        configs['pm2_config'] = json.loads(config_str)
                    else:
                        configs['pm2_config'] = None
                        self.logger.warning(f"Could not parse PM2 config from {pm2_config_path}")
            else:
                configs['pm2_config'] = None
                self.logger.warning(f"PM2 config file not found at {pm2_config_path}")

            # Read Python INI if exists
            if python_config_path.exists():
                config = configparser.ConfigParser()
                config.read(python_config_path)
                configs['python_config'] = {section: dict(config[section]) 
                                         for section in config.sections()}
            else:
                configs['python_config'] = None
                self.logger.warning(f"Python config file not found at {python_config_path}")

            if configs['pm2_config'] is None and configs['python_config'] is None:
                raise FileNotFoundError(
                    f"No configuration files found for process {name}. "
                    f"Checked paths:\n"
                    f"PM2 Config: {pm2_config_path}\n"
                    f"Python Config: {python_config_path}"
                )

            return configs

        except Exception as e:
            self.logger.error(f"Error getting configs for {name}: {str(e)}")
            raise

    def update_process_config(self, name: str, config_data: Dict) -> Dict:
        """Update configuration files for a process"""
        try:
            # Check process exists
            if not any(p['name'] == name for p in self.list_processes()):
                raise ProcessNotFoundError(f"Process {name} not found")

            pm2_config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            python_config_path = Path(f"/home/pm2/pm2-configs/{name}.ini")

            # Update PM2 config if provided
            if 'pm2_config' in config_data and pm2_config_path.exists():
                self._update_pm2_config(pm2_config_path, config_data['pm2_config'])

            # Update Python INI if provided
            if 'python_config' in config_data and python_config_path.exists():
                self._update_python_config(python_config_path, config_data['python_config'])

            # Restart if requested
            if config_data.get('restart', False):
                self.restart_process(name)

            return {
                "message": f"Configuration for {name} updated successfully",
                "config_files": {
                    "pm2_config": str(pm2_config_path),
                    "python_config": str(python_config_path)
                }
            }

        except Exception as e:
            self.logger.error(f"Error updating configs for {name}: {str(e)}")
            raise

    def _update_pm2_config(self, config_path: Path, config_data: Dict):
        """Update PM2 configuration file"""
        with open(config_path, 'r') as f:
            content = f.read()
            match = re.search(r'apps:\s*\[\s*({[^}]+})', content, re.DOTALL)
            if match:
                config_str = match.group(1).replace("'", '"')
                current_config = json.loads(config_str)
                current_config.update(config_data)
                
                with open(config_path, 'w') as f:
                    f.write("module.exports = {\n")
                    f.write("  apps: [\n")
                    f.write("    " + json.dumps(current_config, indent=2).replace('"', "'") + "\n")
                    f.write("  ]\n")
                    f.write("};\n")

    def _update_python_config(self, config_path: Path, config_data: Dict):
        """Update Python configuration file"""
        config = configparser.ConfigParser()
        config.read(config_path)

        for section, data in config_data.items():
            if section not in config:
                config.add_section(section)
            for key, value in data.items():
                if isinstance(value, (list, tuple)):
                    value = ', '.join(map(str, value))
                elif isinstance(value, bool):
                    value = str(value).lower()
                config.set(section, key, str(value))

        with open(config_path, 'w') as f:
            config.write(f)
    
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