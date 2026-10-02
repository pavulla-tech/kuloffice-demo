"""Runs intaka's token panel (demo/token-panel/serve.py) in a container.

serve.py binds 127.0.0.1, which a published port cannot reach. This binds the
container's interfaces instead; the stack publishes the port on the host's
loopback only, so the panel is still unreachable from the network.

serve.py keeps its enrolled devices in .devices.json beside itself, so it runs
from a copy on the panel volume, where those keys survive restarts.
"""
import http.server
import os
import runpy
import shutil

SRC, HERE = "/src", "/panel"

for name in os.listdir(SRC):
    if name != ".devices.json" and os.path.isfile(os.path.join(SRC, name)):
        shutil.copy(os.path.join(SRC, name), os.path.join(HERE, name))


class Server(http.server.ThreadingHTTPServer):
    def __init__(self, address, handler):
        super().__init__(("0.0.0.0", address[1]), handler)


http.server.ThreadingHTTPServer = Server
runpy.run_path(os.path.join(HERE, "serve.py"), run_name="__main__")
