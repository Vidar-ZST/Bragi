"""
mpv subprocess and JSON IPC wrapper class.
Provides audio playback control: load, play, pause, toggle_pause, set_volume,
is_playing, and end-of-file event callback.
Supports Windows named pipes and POSIX UNIX domain sockets without third-party bindings.
"""

import sys
import os
import time
import json
import shutil
import uuid
import threading
import subprocess
from typing import Optional, Callable, Dict, Any

if sys.platform == "win32":
    import msvcrt
    import ctypes
else:
    import socket
    import select


class MpvNotFoundError(Exception):
    """Raised when mpv executable cannot be found on PATH."""
    pass


class MpvPlayer:
    """Controls mpv via its JSON IPC interface over named pipes or UNIX sockets."""

    def __init__(self, on_end_of_file: Optional[Callable[[], None]] = None):
        self._on_end_of_file = on_end_of_file
        self._mpv_process: Optional[subprocess.Popen] = None
        self._pipe_path: Optional[str] = None
        self._pipe_handle = None
        self._sock = None
        self._is_windows = (sys.platform == "win32")

        self._lock = threading.Lock()
        self._request_counter = 0
        self._pending_requests: Dict[int, tuple[threading.Event, Dict[str, Any]]] = {}

        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

        self._is_paused = False
        self._has_file_loaded = False
        self._volume = 100
        self._ignore_next_eof = False

        self._init_mpv()

    @staticmethod
    def find_mpv_path() -> Optional[str]:
        """Locate mpv executable, checking PATH and common fallback locations on Windows."""
        app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        for portable_name in ("mpv.exe", "mpv"):
            portable_path = os.path.join(app_dir, portable_name)
            if os.path.isfile(portable_path):
                return portable_path

        path = shutil.which("mpv")
        if path:
            return path

        if sys.platform == "win32":
            # Refresh PATH from registry in case it was modified recently
            try:
                import winreg
                refreshed_parts = []
                for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root, r"Environment" if root == winreg.HKEY_CURRENT_USER else r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                            val, _ = winreg.QueryValueEx(key, "Path")
                            refreshed_parts.append(val)
                    except Exception:
                        pass
                combined_path = ";".join(refreshed_parts) + ";" + os.environ.get("PATH", "")
                path = shutil.which("mpv", path=combined_path)
                if path:
                    os.environ["PATH"] = combined_path
                    return path
            except Exception:
                pass

            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                winget_dir = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
                if os.path.isdir(winget_dir):
                    for root_dir, _, files in os.walk(winget_dir):
                        if "mpv.exe" in files:
                            return os.path.join(root_dir, "mpv.exe")
                        if "mpv.com" in files:
                            return os.path.join(root_dir, "mpv.com")

            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            candidate = os.path.join(program_files, "mpv", "mpv.exe")
            if os.path.isfile(candidate):
                return candidate

        return None

    def _init_mpv(self):
        """Locate mpv, prepare IPC server, and spawn the subprocess."""
        mpv_path = self.find_mpv_path()
        if not mpv_path:
            raise MpvNotFoundError("mpv executable was not found on your system PATH.")

        uid = uuid.uuid4().hex[:10]
        if self._is_windows:
            self._pipe_path = rf"\\.\pipe\ytmpv_{uid}"
        else:
            self._pipe_path = f"/tmp/ytmpv_{uid}.sock"

        args = [
            mpv_path,
            "--idle=yes",
            "--no-video",
            "--force-window=no",
            "--no-terminal",
            f"--volume={self._volume}",
            f"--input-ipc-server={self._pipe_path}",
        ]

        startupinfo = None
        if self._is_windows:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        self._mpv_process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )

        connected = False
        start_time = time.time()
        while time.time() - start_time < 5.0:
            if self._mpv_process.poll() is not None:
                raise RuntimeError("mpv subprocess terminated unexpectedly during startup.")
            try:
                if self._is_windows:
                    self._pipe_handle = open(self._pipe_path, "r+b", buffering=0)
                else:
                    self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._sock.connect(self._pipe_path)
                connected = True
                break
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                time.sleep(0.08)

        if not connected:
            self.shutdown()
            raise RuntimeError(f"Could not connect to mpv IPC at {self._pipe_path}")

        self._running = True
        self._reader_thread = threading.Thread(target=self._ipc_reader_loop, daemon=True)
        self._reader_thread.start()

        self.send_command(["observe_property", 1, "pause"])
        self.send_command(["observe_property", 2, "volume"])

    def _ipc_reader_loop(self):
        """Continuously reads incoming events and command replies without blocking writes."""
        buffer = b""
        if self._is_windows:
            os_handle = msvcrt.get_osfhandle(self._pipe_handle.fileno())
            avail_bytes = ctypes.c_ulong(0)
            peek_func = ctypes.windll.kernel32.PeekNamedPipe

            while self._running:
                try:
                    success = peek_func(os_handle, None, 0, None, ctypes.byref(avail_bytes), None)
                    if not success:
                        break
                    if avail_bytes.value > 0:
                        chunk = self._pipe_handle.read(avail_bytes.value)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            self._handle_incoming_line(line.decode("utf-8", errors="ignore").strip())
                    else:
                        time.sleep(0.02)
                except Exception:
                    break
        else:
            while self._running:
                try:
                    r, _, _ = select.select([self._sock], [], [], 0.05)
                    if r:
                        chunk = self._sock.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            self._handle_incoming_line(line.decode("utf-8", errors="ignore").strip())
                except Exception:
                    break

    def _handle_incoming_line(self, line: str):
        """Parse JSON response or event and route appropriately."""
        if not line:
            return
        try:
            data = json.loads(line)
        except Exception:
            return

        if "request_id" in data:
            req_id = data["request_id"]
            with self._lock:
                if req_id in self._pending_requests:
                    event, result_box = self._pending_requests[req_id]
                    result_box["data"] = data
                    event.set()

        if "event" in data:
            event_name = data["event"]
            if event_name == "property-change":
                prop = data.get("name")
                val = data.get("data")
                if prop == "pause":
                    self._is_paused = bool(val)
                elif prop == "volume" and val is not None:
                    self._volume = int(round(val))

            elif event_name == "end-file":
                reason = data.get("reason", "")
                # Only trigger on natural eof or stop if not intentionally suppressed
                with self._lock:
                    suppressed = self._ignore_next_eof
                    self._ignore_next_eof = False

                if not suppressed and reason == "eof":
                    self._has_file_loaded = False
                    if self._on_end_of_file:
                        try:
                            self._on_end_of_file()
                        except Exception as e:
                            print(f"[mpv error] Error in on_end_of_file callback: {e}")

    def send_command(self, cmd_args: list, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        """Send an IPC command to mpv with an automatic request_id and wait for response."""
        if not self._running:
            return None

        event = threading.Event()
        result_box: Dict[str, Any] = {}

        with self._lock:
            self._request_counter += 1
            req_id = self._request_counter
            self._pending_requests[req_id] = (event, result_box)
            payload = json.dumps({"command": cmd_args, "request_id": req_id}) + "\n"
            raw = payload.encode("utf-8")
            try:
                if self._is_windows:
                    self._pipe_handle.write(raw)
                else:
                    self._sock.sendall(raw)
            except Exception:
                self._pending_requests.pop(req_id, None)
                return None

        event.wait(timeout)
        with self._lock:
            self._pending_requests.pop(req_id, None)

        return result_box.get("data")

    def load(self, stream_url: str):
        """Load and start playing an audio stream URL."""
        with self._lock:
            self._ignore_next_eof = True
            self._has_file_loaded = True
            self._is_paused = False

        self.send_command(["loadfile", stream_url, "replace"])
        self.send_command(["set_property", "pause", False])

    play_url = load
    play_file = load

    def play(self):
        """Resume playback."""
        if self._has_file_loaded:
            self._is_paused = False
            self.send_command(["set_property", "pause", False])

    def pause(self):
        """Pause playback."""
        if self._has_file_loaded:
            self._is_paused = True
            self.send_command(["set_property", "pause", True])

    def toggle_pause(self):
        """Toggle between play and pause states."""
        if not self._has_file_loaded:
            return
        if self._is_paused:
            self.play()
        else:
            self.pause()

    def stop(self):
        """Stop playback and clear currently playing file."""
        with self._lock:
            self._ignore_next_eof = True
            self._has_file_loaded = False
            self._is_paused = False
        self.send_command(["stop"])

    def set_volume(self, volume: int):
        """Set player volume between 0 and 100."""
        volume = max(0, min(100, int(volume)))
        self._volume = volume
        self.send_command(["set_property", "volume", volume])

    def get_volume(self) -> int:
        """Return the current volume level."""
        return self._volume

    def is_playing(self) -> bool:
        """Return True if a track is loaded and not paused."""
        return self._has_file_loaded and not self._is_paused

    def is_paused(self) -> bool:
        """Return True if playback is paused."""
        return self._is_paused

    def has_file_loaded(self) -> bool:
        """Return True if an audio track is currently loaded."""
        return self._has_file_loaded

    def get_position(self) -> Optional[float]:
        """Query mpv for current playback position in seconds."""
        if not self._has_file_loaded:
            return None
        res = self.send_command(["get_property", "time-pos"], timeout=0.15)
        if res and res.get("error") == "success":
            val = res.get("data")
            if isinstance(val, (int, float)):
                return float(val)
        return None

    def get_duration(self) -> Optional[float]:
        """Query mpv for total track duration in seconds, or None if unknown."""
        if not self._has_file_loaded:
            return None
        res = self.send_command(["get_property", "duration"], timeout=0.15)
        if res and res.get("error") == "success":
            val = res.get("data")
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
        return None

    def seek_to(self, seconds: float):
        """Seek to an absolute timestamp in seconds."""
        if not self._has_file_loaded:
            return
        target = max(0.0, float(seconds))
        self.send_command(["seek", target, "absolute"], timeout=0.5)


    def set_on_end_of_file(self, callback: Callable[[], None]):
        """Register or update the callback invoked when a track finishes."""
        self._on_end_of_file = callback

    def shutdown(self):
        """Clean up IPC connection and terminate mpv subprocess."""
        self._running = False
        if self._pipe_handle:
            try:
                self._pipe_handle.close()
            except Exception:
                pass
            self._pipe_handle = None

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._mpv_process:
            try:
                self._mpv_process.terminate()
                self._mpv_process.wait(timeout=1.5)
            except Exception:
                try:
                    self._mpv_process.kill()
                except Exception:
                    pass
            self._mpv_process = None

        if not self._is_windows and self._pipe_path and os.path.exists(self._pipe_path):
            try:
                os.remove(self._pipe_path)
            except Exception:
                pass
