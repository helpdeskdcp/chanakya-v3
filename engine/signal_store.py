"""
Chanakya v3 — Shared Signal Store
Cross-module signal sharing without circular imports
"""
import threading

_store = {}  # {username: [signals]}
_lock  = threading.Lock()

def update(username, signals):
    with _lock:
        _store[username] = signals

def get(username, fallback="avinash"):
    with _lock:
        return list(_store.get(username, _store.get(fallback, [])))

def get_all():
    with _lock:
        return dict(_store)
