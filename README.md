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

## Setup

1. Clone the repository and navigate to the project directory:
   ```bash
   cd MediaFlow
   ```

2. Install dependencies with uv:
   ```bash
   uv sync
   ```

3. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```

4. Run the application:
   ```bash
   uv run python -m app.main
   ```

5. Run test suite:
   ```bash
   uv run pytest
   ```
