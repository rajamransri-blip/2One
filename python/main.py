"""PTv advanced Android dashboard for the PTv Cloud Control FastAPI API."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Callable

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

APP_NAME = "PTv"
APP_VERSION = "2.0.0"
DEFAULT_SERVER = "https://twoones-l0s0.onrender.com"

BG = (0.035, 0.047, 0.075, 1)
PANEL = (0.065, 0.082, 0.125, 1)
PANEL_2 = (0.09, 0.11, 0.17, 1)
TEXT = (0.92, 0.95, 1, 1)
MUTED = (0.58, 0.64, 0.76, 1)
ACCENT = (0.28, 0.62, 1, 1)
GREEN = (0.2, 0.82, 0.53, 1)
ORANGE = (1, 0.63, 0.24, 1)
RED = (1, 0.3, 0.35, 1)


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(14)
        self.spacing = dp(6)
        with self.canvas.before:
            Color(*PANEL)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self.bg.pos = self.pos
        self.bg.size = self.size


class CloudAPI:
    def __init__(self):
        self.server = DEFAULT_SERVER
        self.token = ""
        self.admin_key = ""

    def configure(self, server: str, token: str, admin_key: str):
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
        response = requests.request(method, self.server + endpoint, headers=headers,
                                    json=payload, timeout=25)
        try:
            data = response.json()
        except ValueError:
            data = {"status_code": response.status_code, "response": response.text}
        if response.status_code >= 400:
            raise RuntimeError(json.dumps(data, indent=2, ensure_ascii=False))
        return data


class BaseScreen(Screen):
    def __init__(self, app, title, **kwargs):
        super().__init__(**kwargs)
        self.ptv = app
        root = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        back = Button(text="‹", size_hint_x=None, width=dp(42), background_normal="", background_color=PANEL_2,
                      color=TEXT, font_size=dp(26))
        back.bind(on_release=lambda *_: self.ptv.show_screen("home"))
        header.add_widget(back)
        header.add_widget(Label(text=f"[b]{title}[/b]", markup=True, color=TEXT, font_size=dp(20), halign="left"))
        root.add_widget(header)
        self.body = BoxLayout(orientation="vertical", spacing=dp(10))
        root.add_widget(self.body)
        self.add_widget(root)

    def load(self):
        pass


class HomeScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "PTv Control Center", name="home", **kwargs)
        self.body.clear_widgets()
        self.body.add_widget(Label(text="[b]FastAPI Cloud Operations[/b]\nYour secure command center", markup=True,
                                   color=MUTED, halign="left", size_hint_y=None, height=dp(45), text_size=(None, None)))
        self.status_card = Card(orientation="vertical", size_hint_y=None, height=dp(118))
        self.status_title = Label(text="● Checking service...", color=TEXT, font_size=dp(18), halign="left")
        self.status_detail = Label(text=DEFAULT_SERVER, color=MUTED, halign="left")
        self.status_card.add_widget(self.status_title)
        self.status_card.add_widget(self.status_detail)
        self.body.add_widget(self.status_card)
        grid = GridLayout(cols=2, spacing=dp(9), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        items = [("▣  DEVICES", "devices"), ("◈  SERVICES", "services"),
                 ("▤  TOKENS", "tokens"), ("≡  ACTIVITY LOGS", "logs"),
                 ("◆  DIAGNOSTICS", "diagnostics"), ("⚙  SETTINGS", "settings")]
        for label, target in items:
            button = Button(text=label, size_hint_y=None, height=dp(62), background_normal="",
                            background_color=PANEL_2, color=TEXT, font_size=dp(13))
            button.bind(on_release=lambda _, t=target: self.ptv.show_screen(t))
            grid.add_widget(button)
        self.body.add_widget(grid)
        self.body.add_widget(Widget())
        refresh = Button(text="REFRESH DASHBOARD", size_hint_y=None, height=dp(50), background_normal="",
                         background_color=ACCENT, color=(1, 1, 1, 1))
        refresh.bind(on_release=lambda *_: self.load())
        self.body.add_widget(refresh)

    def load(self):
        self.ptv.api_call("GET", "/api/v1/dashboard", callback=self.update)

    def update(self, data, error):
        if error:
            self.status_title.text = "● OFFLINE / AUTH REQUIRED"
            self.status_title.color = ORANGE
            self.status_detail.text = str(error)
            return
        self.status_title.text = "● ONLINE"
        self.status_title.color = GREEN
        stats = data.get("summary", {})
        self.status_detail.text = (f"{self.ptv.api.server}\n"
                                   f"Devices {stats.get('devices', 0)}  •  Tokens {stats.get('tokens', 0)}  •  Logs {stats.get('logs', 0)}")


class DataScreen(BaseScreen):
    def __init__(self, app, title, endpoint, **kwargs):
        super().__init__(app, title, **kwargs)
        self.endpoint = endpoint
        self.output = Label(text="Loading...", color=TEXT, halign="left", valign="top", size_hint_y=None,
                            text_size=(None, None))
        scroll = ScrollView()
        scroll.add_widget(self.output)
        self.body.add_widget(scroll)
        refresh = Button(text="REFRESH", size_hint_y=None, height=dp(46), background_normal="",
                         background_color=ACCENT, color=TEXT)
        refresh.bind(on_release=lambda *_: self.load())
        self.body.add_widget(refresh)

    def load(self):
        self.output.text = "Loading..."
        self.ptv.api_call("GET", self.endpoint, callback=self.update)

    def update(self, data, error):
        self.output.text = (f"[b]Request failed[/b]\n{error}" if error else
                            json.dumps(data, indent=2, ensure_ascii=False))
        self.output.markup = not bool(error)
        self.output.texture_update()
        self.output.height = max(dp(160), self.output.texture_size[1] + dp(20))


class TokenScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Token Control", name="tokens", **kwargs)
        intro = Label(text="Admin-only token lifecycle management", color=MUTED, size_hint_y=None, height=dp(28))
        self.body.add_widget(intro)
        row = GridLayout(cols=3, spacing=dp(6), size_hint_y=None, height=dp(45))
        for token_type in ("python", "supabase", "firebase"):
            btn = Button(text=f"CREATE {token_type.upper()}", background_normal="", background_color=PANEL_2, color=TEXT,
                         font_size=dp(10))
            btn.bind(on_release=lambda _, t=token_type: self.create(t))
            row.add_widget(btn)
        self.body.add_widget(row)
        self.output = Label(text="Use the buttons to manage tokens.", color=TEXT, halign="left", valign="top", size_hint_y=None,
                            text_size=(None, None))
        scroll = ScrollView()
        scroll.add_widget(self.output)
        self.body.add_widget(scroll)
        refresh = Button(text="LIST TOKENS", size_hint_y=None, height=dp(46), background_normal="", background_color=ACCENT, color=TEXT)
        refresh.bind(on_release=lambda *_: self.load())
        self.body.add_widget(refresh)

    def load(self):
        self.ptv.api_call("GET", "/api/v1/tokens", admin=True, callback=self.update)

    def create(self, token_type):
        self.ptv.api_call("POST", "/api/v1/tokens", {"type": token_type, "name": f"PTv {token_type} client"},
                          admin=True, callback=self.update)

    def update(self, data, error):
        self.output.text = str(error) if error else json.dumps(data, indent=2, ensure_ascii=False)
        self.output.texture_update()
        self.output.height = max(dp(160), self.output.texture_size[1] + dp(20))


class SettingsScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Connection & Settings", name="settings", **kwargs)
        self.server = self.field("Render API URL")
        self.token = self.field("Bearer token", True)
        self.admin = self.field("Admin key", True)
        self.server.text = app.api.server
        self.body.add_widget(self.label("API SERVER")); self.body.add_widget(self.server)
        self.body.add_widget(self.label("ACCESS TOKEN")); self.body.add_widget(self.token)
        self.body.add_widget(self.label("ADMIN KEY (optional)")); self.body.add_widget(self.admin)
        save = Button(text="SAVE & TEST CONNECTION", size_hint_y=None, height=dp(50), background_normal="", background_color=ACCENT, color=TEXT)
        save.bind(on_release=self.save)
        self.body.add_widget(save)
        self.body.add_widget(Label(text=f"PTv v{APP_VERSION}\nDevice ID: {app.device_id}", color=MUTED, halign="left"))

    @staticmethod
    def label(text):
        return Label(text=text, color=MUTED, halign="left", size_hint_y=None, height=dp(22))

    @staticmethod
    def field(hint, password=False):
        return TextInput(hint_text=hint, password=password, multiline=False, size_hint_y=None, height=dp(44),
                         background_color=PANEL_2, foreground_color=TEXT, hint_text_color=MUTED, cursor_color=ACCENT)

    def load(self):
        self.server.text = self.ptv.api.server
        self.token.text = self.ptv.api.token
        self.admin.text = self.ptv.api.admin_key

    def save(self, *_):
        self.ptv.configure(self.server.text, self.token.text, self.admin.text)
        self.ptv.show_screen("home")


class PTvApp(App):
    title = APP_NAME

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api = CloudAPI()
        self.device_id = str(uuid.uuid4())
        self.store = JsonStore("ptv_settings.json")
        self.screens = {}
        self.sm = None
        self.nav = None

    def build(self):
        Window.clearcolor = BG
        saved = self.store.get("connection") if self.store.exists("connection") else {}
        self.api.configure(saved.get("server", DEFAULT_SERVER), saved.get("token", ""), saved.get("admin", ""))
        root = BoxLayout(orientation="vertical")
        self.sm = ScreenManager(transition=SlideTransition(duration=0.15))
        screens = [HomeScreen(self), DataScreen(self, "Devices", "/api/v1/devices", name="devices"),
                   DataScreen(self, "Service Matrix", "/api/v1/services", name="services"),
                   TokenScreen(self), DataScreen(self, "Activity Logs", "/api/v1/logs", name="logs"),
                   DataScreen(self, "Diagnostics", "/api/v1/diagnostics", name="diagnostics"), SettingsScreen(self)]
        for screen in screens:
            self.screens[screen.name] = screen
            self.sm.add_widget(screen)
        root.add_widget(self.sm)
        self.nav = GridLayout(cols=4, size_hint_y=None, height=dp(54), spacing=dp(3), padding=dp(3))
        for label, target in (("HOME", "home"), ("DEVICES", "devices"), ("SERVICES", "services"), ("SETTINGS", "settings")):
            button = Button(text=label, background_normal="", background_color=PANEL_2, color=TEXT, font_size=dp(10))
            button.bind(on_release=lambda _, t=target: self.show_screen(t))
            self.nav.add_widget(button)
        root.add_widget(self.nav)
        Clock.schedule_once(lambda *_: self.screens["home"].load(), 0.4)
        return root

    def configure(self, server, token, admin):
        self.api.configure(server, token, admin)
        self.store.put("connection", server=self.api.server, token=self.api.token, admin=self.api.admin_key)

    def show_screen(self, name):
        self.sm.current = name
        screen = self.screens.get(name)
        if screen and hasattr(screen, "load"):
            screen.load()

    def api_call(self, method, endpoint, payload=None, admin=False, callback: Callable | None = None):
        def worker():
            try:
                value, error = self.api.request(method, endpoint, payload, admin), None
            except Exception as exc:
                value, error = None, exc
            Clock.schedule_once(lambda _dt: (callback or self.api_result)(value, error), 0)
        threading.Thread(target=worker, daemon=True).start()

    def api_result(self, data, error):
        pass


if __name__ == "__main__":
    PTvApp().run()
