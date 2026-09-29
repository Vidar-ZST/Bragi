"""
Thread-safe playlist & queue manager for the YouTube audio player.
Stores track metadata: {video_id, title, thumbnail_url, channel}.
Preserves tracks in the queue list so users can see, replay, and manage them.
Tracks are only removed when the user explicitly deletes them.
"""

import threading
from typing import Optional, Dict, Any, List


class QueueManager:
    """Thread-safe playlist and queue manager for audio tracks."""

    def __init__(self):
        self._items: List[Dict[str, Any]] = []
        self._current_index: int = -1
        self._lock = threading.Lock()

    def add(self, item: Dict[str, Any]) -> int:
        """Add an item to the end of the queue. Returns the new queue length."""
        with self._lock:
            self._items.append(item)
            return len(self._items)

    def play_index(self, index: int) -> Optional[Dict[str, Any]]:
        """Set the active track index and return the track without removing it."""
        with self._lock:
            if 0 <= index < len(self._items):
                self._current_index = index
                return self._items[index]
            return None

    def get_current_index(self) -> int:
        """Return the index of the currently active track, or -1 if none."""
        with self._lock:
            return self._current_index

    def set_current_index(self, index: int) -> None:
        """Explicitly set the current track index."""
        with self._lock:
            self._current_index = index

    def get_current_track(self) -> Optional[Dict[str, Any]]:
        """Return the currently active track, or None if none."""
        with self._lock:
            if 0 <= self._current_index < len(self._items):
                return self._items[self._current_index]
            return None

    def get_next_track(self) -> Optional[Dict[str, Any]]:
        """Advance to and return the next track in the queue, or None if at the end."""
        with self._lock:
            if not self._items:
                return None
            next_idx = self._current_index + 1
            if next_idx < len(self._items):
                self._current_index = next_idx
                return self._items[next_idx]
            return None

    def peek_next(self) -> Optional[Dict[str, Any]]:
        """Return the next track that will play without advancing the index."""
        with self._lock:
            if not self._items:
                return None
            if self._current_index == -1:
                return self._items[0]
            next_idx = self._current_index + 1
            if next_idx < len(self._items):
                return self._items[next_idx]
            return None

    def remaining_after_next(self) -> int:
        """Return how many tracks remain in the queue after the next one."""
        with self._lock:
            if not self._items:
                return 0
            if self._current_index == -1:
                return max(0, len(self._items) - 1)
            return max(0, len(self._items) - (self._current_index + 2))

    def remove_at(self, index: int) -> Optional[Dict[str, Any]]:
        """Remove and return the item at specific index, maintaining current index integrity."""
        with self._lock:
            if 0 <= index < len(self._items):
                item = self._items.pop(index)
                if len(self._items) == 0:
                    self._current_index = -1
                elif index < self._current_index:
                    self._current_index -= 1
                elif index == self._current_index:
                    if self._current_index >= len(self._items):
                        self._current_index = len(self._items) - 1
                return item
            return None

    def clear(self) -> None:
        """Clear all items from the queue."""
        with self._lock:
            self._items.clear()
            self._current_index = -1

    def is_empty(self) -> bool:
        """Check if the queue has no items."""
        with self._lock:
            return len(self._items) == 0

    def size(self) -> int:
        """Return the number of items currently in the queue."""
        with self._lock:
            return len(self._items)

    def get_items(self) -> List[Dict[str, Any]]:
        """Return a shallow copy list of all items currently in the queue."""
        with self._lock:
            return list(self._items)

    # Aliases
    enqueue = add

    def dequeue(self) -> Optional[Dict[str, Any]]:
        """Compatibility alias: advances to next track."""
        return self.get_next_track()

    def pop(self) -> Optional[Dict[str, Any]]:
        """Compatibility alias: advances to next track."""
        return self.get_next_track()

    def peek(self) -> Optional[Dict[str, Any]]:
        """Compatibility alias: peeks next track."""
        return self.peek_next()
