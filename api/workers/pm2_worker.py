#!/usr/bin/env python3
# workers/pm2_worker.py

import os
import sys
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

class PM2WorkerConfig:
    """Configuration for PM2 Worker"""
    def __init__(self):
        # Base paths
        self.BASE_PATH = Path("/home/pm2")
        self.CONFIG_DIR = self.BASE_PATH / "pm2-configs"
        self.PROCESSES_DIR = self.BASE_PATH / "pm2-processes"
        
        # Logging
        self.LOG_DIR = self.BASE_PATH / "logs"
        self.WORKER_LOG = self.LOG_DIR / "pm2_worker.log"
        self.LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        self.LOG_LEVEL = logging.INFO
        
        # Timeouts
        self.COMMAND_TIMEOUT = 600  # 10 minutes
        self.GIT_TIMEOUT = 300      # 5 minutes
        self.PIP_TIMEOUT = 600      # 10 minutes
        
        # Create necessary directories
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.PROCESSES_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging(config: PM2WorkerConfig) -> logging.Logger:
    """Set up logging for the worker"""
    logger = logging.getLogger('pm2_worker')
    logger.setLevel(config.LOG_LEVEL)
    
    # File handler
    file_handler = logging.FileHandler(config.WORKER_LOG)
    file_handler.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(console_handler)
    
    return logger

class PM2Worker:
    """Independent worker for PM2 process setup"""
    
    def __init__(self):
        self.config = PM2WorkerConfig()
        self.logger = setup_logging(self.config)
        
    def _run_command(self, command: str, cwd: Optional[Path] = None, timeout: Optional[int] = None) -> Dict:
        """Execute a shell command with timeout"""
        try:
            timeout = timeout or self.config.COMMAND_TIMEOUT
            self.logger.info(f"Running command: {command}")
            
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Log command output
            if result.stdout:
                self.logger.debug(f"Command stdout: {result.stdout}")
            if result.stderr:
                self.logger.debug(f"Command stderr: {result.stderr}")
            
            if result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, command, result.stdout, result.stderr
                )
            
            return {
                'success': True,
                'output': result.stdout.strip(),
                'command': command
            }
            
        except subprocess.TimeoutExpired as e:
            error_msg = f"Command timed out after {timeout}s: {command}"
            self.logger.error(error_msg)
            return {'success': False, 'error': error_msg}
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed: {e.stderr}"
            self.logger.error(error_msg)
            return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            self.logger.error(error_msg)
            return {'success': False, 'error': error_msg}

    def setup_process(self, process_config: Dict) -> Dict:
        """Set up a new PM2 process"""
        name = process_config['name']
        self.logger.info(f"Setting up process: {name}")
        
        try:
            # Setup paths
            process_dir = self.config.PROCESSES_DIR / name
            venv_path = process_dir / "venv"
            current_dir = process_dir / "current"
            logs_dir = process_dir / "logs"
            
            # Create directories
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Clone repository
            repo_url = process_config['repository']['url']
            branch = process_config['repository'].get('branch', 'main')
            
            if current_dir.exists():
                shutil.rmtree(current_dir)
            
            clone_result = self._run_command(
                f"git clone -b {branch} {repo_url} {current_dir}",
                timeout=self.config.GIT_TIMEOUT
            )
            if not clone_result['success']:
                return clone_result
            
            # Create virtual environment
            if venv_path.exists():
                shutil.rmtree(venv_path)
                
            venv_result = self._run_command(
                f"python3 -m venv {venv_path}"
            )
            if not venv_result['success']:
                return venv_result
            
            # Install dependencies
            requirements_file = current_dir / "requirements.txt"
            if requirements_file.exists():
                install_result = self._run_command(
                    f"{venv_path}/bin/pip install --upgrade pip && "
                    f"{venv_path}/bin/pip install -r {requirements_file}",
                    cwd=current_dir,
                    timeout=self.config.PIP_TIMEOUT
                )
                if not install_result['success']:
                    return install_result
            
            # Generate PM2 config
            config_file = self.config.CONFIG_DIR / f"{name}.config.js"
            config_content = self._generate_pm2_config(process_config, 
                                                     process_dir, 
                                                     venv_path, 
                                                     logs_dir)
            
            config_file.write_text(config_content)
            
            # Start process with PM2
            start_result = self._run_command(f"pm2 start {config_file}")
            if not start_result['success']:
                return start_result
            
            # Save PM2 process list
            save_result = self._run_command("pm2 save")
            if not save_result['success']:
                self.logger.warning("Failed to save PM2 process list")
            
            return {
                'success': True,
                'message': f"Process {name} setup completed successfully",
                'config_file': str(config_file),
                'process_dir': str(process_dir),
                'venv_path': str(venv_path)
            }
            
        except Exception as e:
            error_msg = f"Process setup failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.cleanup_failed_setup(name)
            return {'success': False, 'error': error_msg}

    def _generate_pm2_config(self, 
                           process_config: Dict, 
                           process_dir: Path,
                           venv_path: Path,
                           logs_dir: Path) -> str:
        """Generate PM2 configuration file content"""
        name = process_config['name']
        script = process_config.get('script', 'app.py')
        env_vars = process_config.get('env_vars', {})
        
        return f'''module.exports = {{
    apps: [{{
        name: "{name}",
        script: "{venv_path}/bin/python",
        args: "{script}",
        cwd: "{process_dir}/current",
        env: {json.dumps(env_vars, indent=8)},
        autorestart: {str(process_config.get('auto_restart', True)).lower()},
        watch: false,
        ignore_watch: [
            "venv",
            "*.pyc",
            "__pycache__",
            "*.log"
        ],
        max_memory_restart: "1G",
        error_file: "{logs_dir}/{name}-error.log",
        out_file: "{logs_dir}/{name}-out.log",
        merge_logs: true,
        time: true,
        log_date_format: "YYYY-MM-DD HH:mm:ss Z"
    }}]
}};'''

    def cleanup_failed_setup(self, name: str) -> None:
        """Clean up after failed process setup"""
        try:
            # Remove process directory
            process_dir = self.config.PROCESSES_DIR / name
            if process_dir.exists():
                shutil.rmtree(process_dir)
            
            # Remove config file
            config_file = self.config.CONFIG_DIR / f"{name}.config.js"
            if config_file.exists():
                config_file.unlink()
            
            # Try to remove from PM2 if it was added
            try:
                self._run_command(f"pm2 delete {name}")
                self._run_command("pm2 save")
            except Exception as e:
                self.logger.warning(f"Failed to remove process from PM2: {str(e)}")
                
            self.logger.info(f"Cleanup completed for {name}")
            
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")

def main():
    """Main entry point for the worker"""
    if len(sys.argv) != 2:
        print("Usage: pm2_worker.py <config_file>")
        sys.exit(1)
    
    config_file = Path(sys.argv[1])
    if not config_file.exists():
        print(f"Config file not found: {config_file}")
        sys.exit(1)
    
    try:
        # Load process configuration
        with open(config_file) as f:
            process_config = json.load(f)
        
        # Initialize and run worker
        worker = PM2Worker()
        result = worker.setup_process(process_config)
        
        # Output result as JSON
        print(json.dumps(result))
        
        # Exit with appropriate status code
        sys.exit(0 if result['success'] else 1)
        
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': f"Worker failed: {str(e)}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()