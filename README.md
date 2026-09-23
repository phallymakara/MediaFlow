# MediaFlow

Desktop Media Downloader built with Python and PySide6.

## Overview

MediaFlow is a desktop GUI application designed to download publicly accessible media from supported platforms. It automatically detects source platforms from input URLs, extracts metadata, provides format and quality selections, and handles background downloads with local history tracking.

## Target Sources

- Social and Video Platforms (supported via yt-dlp):
  - YouTube
  - TikTok
  - Instagram
  - Facebook
  - X (Twitter)
  - Reddit
  - Vimeo
- Short Drama Platforms (supported via custom extractors):
  - DramaBox
  - NetShort
  - FlickReels
  - StardustTV
  - GoodShort
  - DramaWave
  - FreeReels
- Direct Media URLs (MP4, audio, accessible streams)

## Architecture

The application enforces a modular design separating the user interface from extraction, download management, and storage:

```
Desktop GUI (PySide6)
        |
Application Services
        |
Extractor Registry / Download Manager
        |
Extractors (yt-dlp and Custom Extractors)
        |
Normalized Media Information
        |
Media Processing (FFmpeg) and Storage
        |
SQLite History and Metadata
```

## Directory Structure

```
mediaflow/
|-- app/
|   |-- gui/             # PySide6 UI views and widgets
|   |-- core/            # Registry, download orchestration, media models, tasks
|   |-- extractors/      # yt-dlp and platform-specific extractors
|   |-- services/        # FFmpeg, storage, and metadata services
|   |-- database/        # SQLite models and database operations
|   |-- config.py        # Dynamic application configuration
|   `-- main.py          # Application entry point
|-- tests/               # Unit and integration tests
|-- assets/              # Icons and application images
|-- pyproject.toml       # Dependencies and build configuration
`-- README.md
```

## Requirements

- Python 3.13 or newer
- uv package manager
- FFmpeg (installed and available in system PATH or configured via `.env`)

### Platform-Specific Prerequisites

#### Windows
- Install FFmpeg via winget:
  ```powershell
  winget install Gyan.FFmpeg
  ```
- Install uv via PowerShell:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

#### macOS
- Install FFmpeg via Homebrew:
  ```bash
  brew install ffmpeg
  ```
- Install uv:
  ```bash
  brew install uv
  ```
  Or via official installer:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

## Setup and Installation

1. Clone the repository and navigate to the project directory:
   ```bash
   git clone https://github.com/phallymakara/MediaFlow.git
   cd MediaFlow
   ```

2. Install dependencies with uv:
   ```bash
   uv sync
   ```

3. Configure environment settings:
   - On macOS and Linux:
     ```bash
     cp .env.example .env
     ```
   - On Windows (PowerShell):
     ```powershell
     Copy-Item .env.example .env
     ```

4. Run the application:
   ```bash
   uv run python -m app.main
   ```

5. Run test suite:
   ```bash
   uv run pytest
   ```

## License Management Tools (Developer)

Generate customer license keys using the standalone utilities:

- CLI Generator:
  ```bash
  uv run python tools/keygen.py --days 30 --user "CustomerName"
  uv run python tools/keygen.py --lifetime --tier pro
  ```

- GUI Generator:
  ```bash
  uv run python tools/keygen_gui.py
  ```
