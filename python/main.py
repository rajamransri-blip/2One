"""PTv Android client for the PTv Cloud Control FastAPI API."""

from __future__ import annotations

import json
import threading
import uuid

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

APP_NAME = "PTv"
APP_VERSION = "1.0.0"


class CloudAPI:
    def __init__(self) -> None:
        self.server = ""
        self.token = ""
        self.admin_key = ""

    def configure(self, server: str, token: str, admin_key: str) -> None:
        self.server = server.strip().rstrip("/")
        self.token = token.strip()
        self.admin_key = admin_key.strip()

    def request(self, method: str, endpoint: str, payload=None, admin=False):
        if not self.server:
            raise ValueError("Server URL is empty")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if admin and self.admin_key:
            headers["X-Admin-Key"] = self.admin_key
        response = requests.request(
            method,
            self.server + endpoint,
            headers=headers,
            json=payload,
            timeout=25,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"status_code": response.status_code, "response": response.text}
        if response.status_code >= 400:
            raise RuntimeError(json.dumps(data, indent=2, ensure_ascii=False))
        return data


class PTvApp(App):
    title = APP_NAME

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api = CloudAPI()
        self.device_id = str(uuid.uuid4())
        self.server_input = None
        self.token_input = None
        self.admin_input = None
        self.status = None
        self.output = None

    def build(self):
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        root.add_widget(Label(text="[b]PTv[/b]", markup=True, font_size=dp(27), size_hint_y=None, height=dp(48)))
        root.add_widget(Label(text="FastAPI Cloud Control", font_size=dp(14), size_hint_y=None, height=dp(28)))
        self.server_input = self.field("https://your-server.onrender.com", password=False)
        self.token_input = self.field("Bearer token (ptv_live_...)", password=True)
        self.admin_input = self.field("Admin key (for token management)", password=True)
        root.add_widget(self.server_input)
        root.add_widget(self.token_input)
        root.add_widget(self.admin_input)
        connect = Button(text="CONNECT / CHECK SERVER", size_hint_y=None, height=dp(48))
        connect.bind(on_release=self.connect)
        root.add_widget(connect)
        self.status = Label(text="● Offline", size_hint_y=None, height=dp(30))
        root.add_widget(self.status)

        scroll = ScrollView()
        menu = GridLayout(cols=2, spacing=dp(6), size_hint_y=None)
        menu.bind(minimum_height=menu.setter("height"))
        actions = [
            ("Server status", lambda *_: self.call("GET", "/api/v1/server")),
            ("Register device", self.register_device),
            ("Devices", lambda *_: self.call("GET", "/api/v1/devices")),
            ("Services", lambda *_: self.call("GET", "/api/v1/services")),
            ("Logs", lambda *_: self.call("GET", "/api/v1/logs")),
            ("List tokens", lambda *_: self.call("GET", "/api/v1/tokens", admin=True)),
            ("Create Python token", lambda *_: self.create_token("python")),
            ("Create Supabase token", lambda *_: self.create_token("supabase")),
            ("Create Firebase token", lambda *_: self.create_token("firebase")),
            ("Settings", self.settings),
        ]
        for text, callback in actions:
            button = Button(text=text, size_hint_y=None, height=dp(48))
            button.bind(on_release=callback)
            menu.add_widget(button)
        scroll.add_widget(menu)
        root.add_widget(scroll)
        self.output = Label(text="Ready.", halign="left", valign="top", size_hint_y=None, height=dp(150), text_size=(None, None))
        root.add_widget(self.output)
        return root

    @staticmethod
    def field(hint: str, password: bool) -> TextInput:
        return TextInput(hint_text=hint, password=password, multiline=False, size_hint_y=None, height=dp(44))

    def configure(self):
        self.api.configure(self.server_input.text, self.token_input.text, self.admin_input.text)

    def show(self, value):
        self.output.text = json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)

    def popup(self, title, message):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        box.add_widget(Label(text=str(message)))
        close = Button(text="CLOSE", size_hint_y=None, height=dp(44))
        box.add_widget(close)
        popup = Popup(title=title, content=box, size_hint=(0.92, 0.65))
        close.bind(on_release=popup.dismiss)
        popup.open()

    def run_async(self, function, callback=None):
        def worker():
            try:
                result, error = function(), None
            except Exception as exc:  # network errors are shown in the UI
                result, error = None, exc
            Clock.schedule_once(lambda _dt: (callback or self.operation_result)(result, error), 0)
        threading.Thread(target=worker, daemon=True).start()

    def connect(self, *_):
        self.configure()
        self.status.text = "● Connecting..."
        self.run_async(lambda: self.api.request("GET", "/api/v1/server"), self.connection_result)

    def connection_result(self, data, error):
        if error:
            self.status.text = "● Offline"
            self.popup("Connection failed", error)
            return
        self.status.text = "● ONLINE"
        self.show(data)

    def call(self, method, endpoint, payload=None, admin=False):
        self.configure()
        self.run_async(lambda: self.api.request(method, endpoint, payload, admin=admin))

    def create_token(self, token_type):
        self.call("POST", "/api/v1/tokens", {"type": token_type, "name": f"{APP_NAME} {token_type}"}, admin=True)

    def register_device(self, *_):
        self.call("POST", "/api/v1/devices/register", {
            "device_id": self.device_id,
            "device_name": "PTv Android",
            "platform": "Android",
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
        })

    def settings(self, *_):
        self.popup("PTv Settings", f"Version: {APP_VERSION}\n\nDevice ID:\n{self.device_id}")

    def operation_result(self, data, error):
        if error:
            self.popup("API error", error)
            return
        self.show(data)


if __name__ == "__main__":
    PTvApp().run()
