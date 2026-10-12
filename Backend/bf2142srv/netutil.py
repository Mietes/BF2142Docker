import socketserver
import sys


class TCPServer(socketserver.ThreadingTCPServer):
    # На Windows SO_REUSEADDR даёт второму процессу занять тот же порт — не нужно.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


class UDPServer(socketserver.UDPServer):
    allow_reuse_address = sys.platform != "win32"
