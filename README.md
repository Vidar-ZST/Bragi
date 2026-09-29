# Bragi

A minimalist, high-performance desktop YouTube audio player built for background listening. Streams audio directly through headless `mpv` without browser or video rendering overhead.

---

## Features

- **Lightweight**: Near-zero CPU and memory usage; no Chromium or Electron.
- **Global Overlay**: Bring up or hide the player anytime with `Ctrl+Shift+P` (or custom hotkey), even in full-screen games.
- **Dual Loading**: Search YouTube tracks by title or paste links directly (including Shorts).
- **Interactive Queue**: Reorder-free playlist with direct track switching and individual removal.
- **System Tray**: Minimizes cleanly to the Windows notification tray.

---

## Prerequisites

- **Python 3.10+**
- **mpv media player** on your `PATH` or placed as `mpv.exe` in the application folder:
  ```powershell
  winget install mpv-player.mpv-CI.MSVC
  ```

---

## Installation & Setup

```bash
git clone https://github.com/Vidar-ZST/bragi.git
cd bragi
pip install -r requirements.txt
```

### YouTube API Key (Optional)
Pasting links works without an API key. To enable the search bar, copy `config.json.example` to `config.json` and add your YouTube Data API v3 key:

```json
{
  "youtube_api_key": "YOUR_API_KEY",
  "hotkey": "ctrl+shift+p",
  "always_on_top": false
}
```

---

## Usage

```bash
python main.py
```

## Build Standalone Executable (.exe)

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "Bragi" --icon=icon.ico --add-data "icon.png;." --add-data "icon.ico;." main.py
```

The compiled binary will be placed in `dist/Bragi.exe`.

---

## License

MIT
