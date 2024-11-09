# PM2 Controller API Documentation

## Project Overview
The PM2 Controller API is a Flask-based REST API that provides a web interface for managing PM2 processes. It allows users to start, stop, restart, and monitor PM2-managed applications through HTTP endpoints.

## Project Structure
```
pm2_controller/
├── api/
│   ├── models/
│   │   ├── process.py      # API models for process data
│   │   └── error.py        # API models for error responses
│   └── routes/
│       ├── health.py       # Health check endpoints
│       ├── processes.py    # Process management endpoints
│       └── logs.py         # Log management endpoints
├── core/
│   ├── config.py          # Application configuration
│   ├── exceptions.py      # Custom exception classes
│   └── logging.py         # Logging configuration
├── services/
│   ├── pm2.py            # PM2 command execution service
│   ├── process_manager.py # Process management service
│   └── log_manager.py    # Log management service
└── app.py                # Main application entry point
```

## File Descriptions

### Main Application (app.py)
```python
# Main application entry point that:
# - Initializes Flask application
# - Sets up API documentation
# - Configures CORS
# - Initializes services
# - Registers routes
# - Starts the server
```

Key responsibilities:
1. Application initialization
2. Service dependency management
3. Route registration
4. API documentation setup

### Core Module

#### config.py
```python
# Configuration management:
# - Loads environment variables
# - Defines application settings
# - Manages file paths
# - Sets up operational parameters
```

Important settings:
- Server configuration (host, port)
- Logging settings
- PM2 configuration
- File paths
- Operational limits

#### exceptions.py
```python
# Custom exception classes:
# - PM2Error: Base exception
# - ProcessNotFoundError: Process not found
# - ProcessAlreadyExistsError: Duplicate process
# - PM2CommandError: Command execution failed
# - PM2TimeoutError: Command timeout
```

#### logging.py
```python
# Logging configuration:
# - Sets up log handlers
# - Configures log formats
# - Manages log rotation
# - Defines log levels
```

### Services Module

#### pm2.py
```python
# PM2 service that:
# - Executes PM2 commands
# - Handles command retry logic
# - Parses command output
# - Manages process listing
# - Handles process operations
```

Key features:
- Command execution
- Error handling
- Process management
- Output parsing

#### process_manager.py
```python
# Process management service:
# - Creates process configurations
# - Updates process settings
# - Manages process lifecycle
# - Handles process files
```

Responsibilities:
- Config file creation
- Process creation
- Settings management
- File operations

#### log_manager.py
```python
# Log management service:
# - Reads process logs
# - Clears log files
# - Manages log rotation
# - Handles log querying
```

### API Module

#### models/process.py
```python
# API models for:
# - Process information
# - Process configuration
# - Process monitoring
# - Process creation/updates
```

Model types:
1. Base environment model
2. Process monitoring model
3. PM2 environment model
4. Process creation model

#### models/error.py
```python
# API models for:
# - Error responses
# - Error details
# - Error timestamps
```

#### routes/processes.py
```python
# Process management endpoints:
# GET    /processes/               # List all processes
# POST   /processes/               # Create new process
# GET    /processes/<name>         # Get process details
# DELETE /processes/<name>         # Delete process
# POST   /processes/<name>/start   # Start process
# POST   /processes/<name>/stop    # Stop process
# POST   /processes/<name>/restart # Restart process
```

#### routes/health.py
```python
# Health check endpoints:
# GET /health/  # Check API health status
```

#### routes/logs.py
```python
# Log management endpoints:
# GET    /logs/<process_name>  # Get process logs
# DELETE /logs/<process_name>  # Clear process logs
```

## API Usage

### Process Management
```bash
# List all processes
GET /api/processes/

# Create new process
POST /api/processes/
{
  "name": "myapp",
  "script": "app.py",
  "interpreter": "python3"
}

# Get process details
GET /api/processes/myapp

# Start process
POST /api/processes/myapp/start

# Stop process
POST /api/processes/myapp/stop

# Restart process
POST /api/processes/myapp/restart
```

### Log Management
```bash
# Get process logs
GET /api/logs/myapp?lines=100

# Clear process logs
DELETE /api/logs/myapp
```

### Health Checks
```bash
# Check API health
GET /api/health/
```

## Error Handling
All endpoints use consistent error response format:
```json
{
  "error": "Error message",
  "error_type": "ErrorClassName",
  "timestamp": "2024-11-09T14:00:00Z",
  "details": {
    "process_name": "myapp",
    "additional_info": "..."
  }
}
```

## Dependencies
- Flask: Web framework
- Flask-RESTX: API documentation and REST tools
- PM2: Process manager
- Python-dotenv: Environment configuration