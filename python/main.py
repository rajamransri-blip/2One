"""PTv FastAPI 2.0 no-login mobile cloud control client."""

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


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(padding=dp(14), spacing=dp(6), **kwargs)
        with self.canvas.before:
            Color(*PANEL)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self.sync, size=self.sync)

    def sync(self, *_):
        self.bg.pos, self.bg.size = self.pos, self.size


class CloudAPI:
    def __init__(self):
        self.server = DEFAULT_SERVER
        self.token = ""

    def configure(self, server: str, token: str = ""):
        self.server, self.token = server.strip().rstrip("/"), token.strip()

    def request(self, method: str, endpoint: str, payload=None):
        if not self.server:
            raise ValueError("Server URL is empty")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = requests.request(method, self.server + endpoint, headers=headers, json=payload, timeout=25)
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
        back = Button(text="‹", size_hint_x=None, width=dp(42), background_normal="", background_color=PANEL_2, color=TEXT, font_size=dp(26))
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
        super().__init__(app, "PTv  •  FastAPI 2.0", name="home", **kwargs)
        self.body.add_widget(Label(text="[b]LIVE CLOUD CONTROL[/b]\nNo login required • secure device token stored locally", markup=True, color=MUTED, halign="left", size_hint_y=None, height=dp(48)))
        self.status = Card(orientation="vertical", size_hint_y=None, height=dp(126))
        self.title_label = Label(text="● CONNECTING...", color=ORANGE, font_size=dp(19), halign="left")
        self.detail = Label(text=DEFAULT_SERVER, color=MUTED, halign="left")
        self.status.add_widget(self.title_label); self.status.add_widget(self.detail)
        self.body.add_widget(self.status)
        grid = GridLayout(cols=2, spacing=dp(9), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for text, target in (("▣  DEVICES", "devices"), ("◈  SERVICES", "services"), ("▤  API KEY", "tokens"), ("≡  ACTIVITY", "logs"), ("◆  LIVE DIAGNOSTICS", "diagnostics"), ("⚙  SETTINGS", "settings")):
            b = Button(text=text, size_hint_y=None, height=dp(62), background_normal="", background_color=PANEL_2, color=TEXT, font_size=dp(12))
            b.bind(on_release=lambda _, t=target: self.ptv.show_screen(t)); grid.add_widget(b)
        self.body.add_widget(grid); self.body.add_widget(Widget())
        refresh = Button(text="REFRESH LIVE STATUS", size_hint_y=None, height=dp(50), background_normal="", background_color=ACCENT, color=TEXT)
        refresh.bind(on_release=lambda *_: self.load()); self.body.add_widget(refresh)

    def load(self):
        self.ptv.ensure_token(lambda: self.ptv.api_call("GET", "/api/v1/dashboard", self.update))

    def update(self, data, error):
        if error:
            self.title_label.text, self.title_label.color = "● OFFLINE / RETRY", ORANGE
            self.detail.text = str(error); return
        self.title_label.text, self.title_label.color = "● LIVE  •  FASTAPI 2.0", GREEN
        s = data.get("summary", {})
        self.detail.text = f"{self.ptv.api.server}\nDevices {s.get('devices', 0)}  •  Active keys {s.get('tokens', 0)}  •  Events {s.get('logs', 0)}"


class DataScreen(BaseScreen):
    def __init__(self, app, title, endpoint, **kwargs):
        super().__init__(app, title, **kwargs); self.endpoint = endpoint
        self.output = Label(text="Loading...", color=TEXT, halign="left", valign="top", size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.output); self.body.add_widget(scroll)
        b = Button(text="REFRESH LIVE DATA", size_hint_y=None, height=dp(46), background_normal="", background_color=ACCENT, color=TEXT)
        b.bind(on_release=lambda *_: self.load()); self.body.add_widget(b)

    def load(self):
        self.output.text = "Loading..."
        self.ptv.ensure_token(lambda: self.ptv.api_call("GET", self.endpoint, self.update))

    def update(self, data, error):
        self.output.text = str(error) if error else json.dumps(data, indent=2, ensure_ascii=False)
        self.output.texture_update(); self.output.height = max(dp(180), self.output.texture_size[1] + dp(20))


class ServicesScreen(DataScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Cloud Services  •  LIVE", "/api/v1/services", name="services", **kwargs)

    def update(self, data, error):
        if error: return super().update(data, error)
        services = data.get("services", {})
        lines = ["[b]LIVE SERVICE MATRIX[/b]", ""]
        for name, info in services.items():
            if isinstance(info, dict):
                icon = "●" if info.get("enabled") else "○"
                lines.append(f"{icon}  {name.upper()}  —  {info.get('status', 'unknown')}")
                if name in ("firebase", "supabase"):
                    lines.append(f"    Database: {'READY' if info.get('database') else 'OFF'}   Storage: {'READY' if info.get('storage') else 'OFF'}")
            else: lines.append(f"●  {name.upper()}  —  {'READY' if info else 'OFF'}")
        self.output.text = "\n".join(lines); self.output.markup = True; self.output.texture_update(); self.output.height = dp(220)


class TokenScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Service API Key", name="tokens", **kwargs)
        self.body.add_widget(Label(text="Generate one reusable PTv API key for your own apps. No login screen.", color=MUTED, halign="left", size_hint_y=None, height=dp(42)))
        self.output = Label(text="Your device key is stored locally and used automatically.", color=TEXT, halign="left", valign="top", size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.output); self.body.add_widget(scroll)
        gen = Button(text="GENERATE NEW APP API KEY", size_hint_y=None, height=dp(52), background_normal="", background_color=ACCENT, color=TEXT)
        gen.bind(on_release=lambda *_: self.generate()); self.body.add_widget(gen)

    def load(self):
        self.output.text = "Current key: " + (self.ptv.api.token[:18] + "…" if self.ptv.api.token else "Not created yet")

    def generate(self):
        self.ptv.provision(lambda data, error: self.update(data, error))

    def update(self, data, error):
        self.output.text = str(error) if error else json.dumps(data, indent=2, ensure_ascii=False)
        self.output.texture_update(); self.output.height = max(dp(180), self.output.texture_size[1] + dp(20))


class SettingsScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Settings  •  Connection", name="settings", **kwargs)
        self.server = TextInput(text=app.api.server, hint_text="Render API URL", multiline=False, size_hint_y=None, height=dp(46), background_color=PANEL_2, foreground_color=TEXT, hint_text_color=MUTED)
        self.body.add_widget(Label(text="API SERVER", color=MUTED, size_hint_y=None, height=dp(24))); self.body.add_widget(self.server)
        self.body.add_widget(Label(text="Services are configured securely on the server (Firebase/Supabase).", color=MUTED, halign="left", size_hint_y=None, height=dp(48)))
        save = Button(text="SAVE & CHECK LIVE CONNECTION", size_hint_y=None, height=dp(50), background_normal="", background_color=ACCENT, color=TEXT)
        save.bind(on_release=self.save); self.body.add_widget(save)
        self.info = Label(text=f"PTv FastAPI 2.0\nDevice: {app.device_id}", color=MUTED, halign="left"); self.body.add_widget(self.info)

    def load(self): self.server.text = self.ptv.api.server

    def save(self, *_):
        self.ptv.configure(self.server.text); self.ptv.show_screen("home")


class PTvApp(App):
    title = APP_NAME

    def __init__(self, **kwargs):
        super().__init__(**kwargs); self.api = CloudAPI(); self.device_id = str(uuid.uuid4()); self.store = JsonStore("ptv_settings.json"); self.screens = {}

    def build(self):
        Window.clearcolor = BG
        saved = self.store.get("connection") if self.store.exists("connection") else {}
        self.api.configure(saved.get("server", DEFAULT_SERVER), saved.get("token", ""))
        root = BoxLayout(orientation="vertical"); self.sm = ScreenManager(transition=SlideTransition(duration=0.15))
        screens = [HomeScreen(self), DataScreen(self, "Devices  •  LIVE", "/api/v1/devices", name="devices"), ServicesScreen(self), TokenScreen(self), DataScreen(self, "Activity  •  LIVE", "/api/v1/logs", name="logs"), DataScreen(self, "Diagnostics  •  LIVE", "/api/v1/diagnostics", name="diagnostics"), SettingsScreen(self)]
        for screen in screens: self.screens[screen.name] = screen; self.sm.add_widget(screen)
        root.add_widget(self.sm)
        nav = GridLayout(cols=4, size_hint_y=None, height=dp(54), spacing=dp(3), padding=dp(3))
        for label, target in (("HOME", "home"), ("DEVICES", "devices"), ("SERVICES", "services"), ("SETTINGS", "settings")):
            b = Button(text=label, background_normal="", background_color=PANEL_2, color=TEXT, font_size=dp(10)); b.bind(on_release=lambda _, t=target: self.show_screen(t)); nav.add_widget(b)
        root.add_widget(nav); Clock.schedule_once(lambda *_: self.screens["home"].load(), 0.5); return root

    def configure(self, server):
        self.api.configure(server, self.api.token); self.store.put("connection", server=self.api.server, token=self.api.token)

    def show_screen(self, name):
        self.sm.current = name; screen = self.screens.get(name)
        if screen and hasattr(screen, "load"): screen.load()

    def provision(self, callback=None):
        payload = {"device_id": self.device_id, "device_name": "PTv Mobile", "platform": "Android", "app_version": APP_VERSION}
        self.api_call("POST", "/api/v1/provision", lambda data, error: self._provisioned(data, error, callback), payload=payload, allow_empty=True)

    def _provisioned(self, data, error, callback):
        if not error and data.get("token"):
            self.api.token = data["token"]; self.store.put("connection", server=self.api.server, token=self.api.token)
        if callback: callback(data, error)

    def ensure_token(self, callback):
        callback() if self.api.token else self.provision(lambda _data, error: callback() if not error else self.api_result(None, error))

    def api_call(self, method, endpoint, callback=None, payload=None, allow_empty=False):
        def worker():
            try: value, error = self.api.request(method, endpoint, payload), None
            except Exception as exc: value, error = None, exc
            Clock.schedule_once(lambda _dt: (callback or self.api_result)(value, error), 0)
        threading.Thread(target=worker, daemon=True).start()

    def api_result(self, data, error): pass


if __name__ == "__main__":
    PTvApp().run()
