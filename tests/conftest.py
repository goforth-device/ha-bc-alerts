"""Make custom_components importable from the repository root."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

if sys.platform == "win32":
    # Windows event loops need a local socket pair, which the harness blocks.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None
    pytest_socket.socket_allow_hosts = lambda *args, **kwargs: None
