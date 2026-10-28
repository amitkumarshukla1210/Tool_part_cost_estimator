from threading import Event

_stop_requested = Event()


def request_shutdown() -> None:
    _stop_requested.set()


def stop_requested() -> bool:
    return _stop_requested.is_set()
