# Pintuxx Game Launcher - README

## Overview

Pintuxx Game Launcher is a modern, cross-platform game management application built with Python and Tkinter. It provides users with a centralized platform to discover, install, and launch games from a remote repository with secure download capabilities and automatic update management.

## Features

### Core Functionality
- **Game Discovery**: Browse available games from a remote server with detailed information
- **Secure Downloads**: MD5 checksum verification for all game files
- **Installation Management**: Organized game installation with version control
- **Progress Tracking**: Real-time download progress with queue management
- **Auto-Launch**: Direct game execution from the launcher

### Security
- SSL/TLS support with configurable certificate verification
- File integrity validation through checksum verification
- Secure HTTP request handling with proper error management

### Update System
- **Launcher Auto-Updates**: Automatic version checking and update installation
- **Background Checks**: Daily update verification without user intervention
- **Safe Update Process**: Atomic updates with rollback capability
- **Version Comparison**: Semantic versioning support

### User Interface
- Modern dark theme with consistent styling
- Responsive game card layout with scrollable interface
- Real-time download queue visualization
- Intuitive installation and launch controls

## System Requirements

### Minimum Requirements
- **OS**: Windows 10/11, Linux, or macOS
- **Python**: 3.8 or higher
- **RAM**: 4 GB minimum
- **Storage**: Sufficient space for game installations (varies by game)

### Dependencies
- tkinter (usually included with Python)
- ssl (standard library)
- http.client (standard library)
- hashlib (standard library)
- zipfile (standard library)
- threading (standard library)
- json (standard library)
- logging (standard library)

## Installation

### Standard Installation
1. Ensure Python 3.8+ is installed on your system
2. Download the launcher executable or source code
3. Run `launcher.py` to start the application

### Development Installation
```bash
git clone <repository-url>
cd pintuxx-launcher
python launcher.py
```

## Configuration

### Installation Directory
- Default: `./apps/`
- Customizable through Settings menu
- Games are organized in `[install_dir]/[game_name]/[version]/` structure

### Cache Management
- Game metadata cached locally in `games_cache.json`
- Automatic cache updates when server is available
- Fallback to cached data when offline

## Usage

### Browsing Games
1. Launch the application
2. Available games are displayed in scrollable cards
3. View game details: name, version, description, system requirements

### Installing Games
1. Click "Install" on desired game card
2. Monitor progress in "Active Downloads" section
3. Download supports resumption and parallel downloads (up to 3 simultaneous)

### Launching Games
1. Installed games show "Launch" button instead of "Install"
2. Click "Launch" to start the game executable
3. Games run in their respective installation directories

### Managing Updates
- Automatic daily checks for launcher updates
- Manual update checks via File → Check for Updates
- Secure update process with integrity verification

## Technical Architecture

### Component Structure
- **PintuxxGameLauncher**: Main application controller
- **GameManager**: Handles installation, caching, and file management
- **SecureRequestHandler**: Manages HTTP/HTTPS communications
- **DownloadWorker**: Threaded download operations
- **GameCard**: UI component for game representation

### Security Implementation
- Configurable SSL verification
- MD5 checksum validation for all downloads
- Secure file extraction with error handling
- Protected temporary file management

### Update Mechanism
1. Version comparison using semantic versioning
2. Secure download with checksum verification
3. Atomic replacement using batch scripts (Windows)
4. Automatic restart and cleanup

## File Structure
```
pintuxx-launcher/
├── launcher.py              # Main application
├── apps/                    # Default installation directory
│   ├── games_cache.json     # Local game metadata cache
│   └── [game-name]/         # Game installations
├── launcher.log            # Application log file
└── last_update_check.txt   # Update check timestamp
```

## Error Handling

### Network Issues
- Graceful fallback to cached data
- Clear error messages for connection failures
- Automatic retry mechanisms for downloads

### File Operations
- Safe temporary file handling
- Proper cleanup on installation failure
- Checksum verification before file operations

### Application Errors
- Comprehensive logging to `launcher.log`
- User-friendly error dialogs
- Recovery from corrupted downloads

## Development

### Extending the Launcher
- Add new game cards by implementing the GameCard class
- Modify themes through the ModernTheme class
- Extend download protocols in SecureRequestHandler

### Server Requirements
- HTTP/HTTPS server hosting `games.json`
- Structured JSON response with game metadata
- File server for game downloads

### Building Executables
Use pyinstaller or similar tools to create standalone executables:
```bash
pyinstaller --onefile --windowed launcher.py
```

## Troubleshooting

### Common Issues
- **Download failures**: Check internet connection and server availability
- **Launch errors**: Verify game executables exist in installation directory
- **Update problems**: Ensure write permissions for launcher directory

### Logs
Check `launcher.log` for detailed error information and debugging data.

## License

This project is proprietary software. All rights reserved.

## Support

For technical support or issues, contact the development team with relevant log files and system information.
