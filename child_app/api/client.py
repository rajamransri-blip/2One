"""Shared network contract. Tokens remain in memory and are never saved to APK or disk."""
import ipaddress
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class APIError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, data_dir):
        self.url_file = os.path.join(data_dir, "server_url.txt")
        saved = open(self.url_file, encoding="utf8").read().strip() if os.path.exists(self.url_file) else ""
        self.base = saved or os.getenv("SERVER_URL", "http://10.0.2.2:8000")
        self.access = None
        self.refresh = None
        self.user_id = None
        self.role = None
        self.lock = threading.RLock()

    def set_url(self, url):
        url = url.rstrip("/").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise APIError("Enter a valid HTTPS server address")
        if parsed.scheme == "http":
            try:
                private = ipaddress.ip_address(parsed.hostname).is_private
            except ValueError:
                private = parsed.hostname == "localhost"
            if not private:
                raise APIError("Public servers must use HTTPS")
        with open(self.url_file, "w", encoding="utf8") as output:
            output.write(url)
        os.chmod(self.url_file, 0o600)
        self.base = url
        self.access = self.refresh = None

    def _send(self, method, path, data=None, token=None, content_type="application/json"):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if data is not None:
            body = data if isinstance(data, bytes) else json.dumps(data).encode("utf8")
            headers["Content-Type"] = content_type
        request = Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=12) as response:
                result = response.read()
                return json.loads(result) if result else {}
        except HTTPError as error:
            try:
                detail = json.loads(error.read()).get("detail", "Request rejected")
            except (ValueError, UnicodeError):
                detail = "Request rejected"
            raise APIError(str(detail), error.code) from None
        except (URLError, TimeoutError, OSError) as error:
            raise APIError("OFFLINE — check network and server address") from error

    def request(self, method, path, data=None):
        with self.lock:
            token = self.access
            try:
                return self._send(method, path, data, token)
            except APIError as error:
                if error.status != 401 or not self.refresh:
                    raise
                renewed = self._send("POST", "/auth/refresh", {"refresh_token": self.refresh})
                self.access, self.refresh = renewed["access_token"], renewed["refresh_token"]
                return self._send(method, path, data, self.access)

    def login(self, email, password, role):
        result = self._send("POST", "/auth/login", {"email": email, "password": password})
        if result["role"] != role:
            raise APIError("Use the matching parent or child app", 403)
        self.access, self.refresh = result["access_token"], result["refresh_token"]
        self.user_id, self.role = result["user_id"], result["role"]
        return result

    def register(self, email, password, role):
        return self._send("POST", "/auth/register", {"email": email, "password": password, "role": role})

    def logout(self):
        if self.refresh:
            try:
                self._send("POST", "/auth/logout", {"refresh_token": self.refresh}, self.access)
            except APIError:
                self.refresh = None  # offline logout still clears all in-memory credentials
        self.access = self.refresh = self.user_id = self.role = None

    def upload(self, kind, content, mime, filename):
        boundary = "safety" + os.urandom(12).hex()
        payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                   f"Content-Type: {mime}\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self._send("POST", "/media/" + kind, payload, self.access, "multipart/form-data; boundary=" + boundary)


class SocketFeed:
    def __init__(self, client, on_event):
        self.client = client
        self.on_event = on_event
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _loop(self):
        import websocket
        delay = 1
        while not self.stop_event.is_set() and self.client.access:
            address = self.client.base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
            connection = None
            try:
                connection = websocket.create_connection(address, timeout=35)
                connection.send(json.dumps({"type": "auth", "token": self.client.access}))
                ready = json.loads(connection.recv())
                if ready.get("type") != "ready":
                    raise APIError("WebSocket authentication failed")
                delay = 1
                self.on_event(ready)
                while not self.stop_event.is_set():
                    try:
                        frame = json.loads(connection.recv())
                    except websocket.WebSocketTimeoutException:
                        connection.send(json.dumps({"type": "ping"}))
                        continue
                    if frame.get("type") == "ping":
                        connection.send(json.dumps({"type": "pong"}))
                    else:
                        self.on_event(frame)
            except (OSError, ValueError, APIError, websocket.WebSocketException):
                if self.stop_event.wait(delay):
                    break
                delay = min(delay * 2, 60)
            finally:
                if connection:
                    connection.close()
