"""PTv FastAPI 2.0 responsive no-login mobile cloud console."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Callable

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
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


def fit(widget, *_):
    widget.text_size = (max(dp(20), widget.width - dp(18)), None)


class PTvButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_color", PANEL_2)
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("font_size", sp(13))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(52))
        super().__init__(**kwargs)
        self.halign = "center"
        self.valign = "middle"
        self.shorten = True
        self.shorten_from = "right"
        self.bind(size=lambda *_: setattr(self, "text_size", (self.width - dp(18), self.height - dp(8))))


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(padding=dp(13), spacing=dp(6), **kwargs)
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

    def configure(self, server, token=""):
        self.server, self.token = server.strip().rstrip("/"), token.strip()

    def request(self, method, endpoint, payload=None):
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


class Header(BoxLayout):
    def __init__(self, app, title, **kwargs):
        super().__init__(size_hint_y=None, height=dp(48), spacing=dp(8), **kwargs)
        back = PTvButton(text="‹", size_hint_x=None, width=dp(42), font_size=sp(25))
        back.bind(on_release=lambda *_: app.show("home"))
        self.add_widget(back)
        label = Label(text=f"[b]{title}[/b]", markup=True, color=TEXT, font_size=sp(19), halign="left", valign="middle")
        label.bind(size=fit)
        self.add_widget(label)


class BaseScreen(Screen):
    def __init__(self, app, title, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(9))
        root.add_widget(Header(app, title))
        self.body = BoxLayout(orientation="vertical", spacing=dp(9))
        root.add_widget(self.body)
        self.add_widget(root)

    def load(self):
        pass


class HomeScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "PTv  •  FastAPI 2.0", name="home", **kwargs)
        intro = Label(text="[b]CLOUD CONTROL[/b]\nNo login • your device key is stored securely", markup=True, color=MUTED, font_size=sp(13), halign="left", valign="middle", size_hint_y=None, height=dp(45))
        intro.bind(size=fit); self.body.add_widget(intro)
        self.live = Card(orientation="vertical", size_hint_y=None, height=dp(105))
        self.live_title = Label(text="● CONNECTING...", color=ORANGE, font_size=sp(18), halign="left", valign="middle")
        self.live_detail = Label(text=DEFAULT_SERVER, color=MUTED, font_size=sp(12), halign="left", valign="middle")
        for label in (self.live_title, self.live_detail): label.bind(size=fit); self.live.add_widget(label)
        self.body.add_widget(self.live)
        grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for text, screen in (("API KEY", "key"), ("DATABASE", "database"), ("SUPABASE KEY", "supabase"), ("SQL EDITOR", "sql")):
            button = PTvButton(text=text, height=dp(68), font_size=sp(14))
            button.bind(on_release=lambda _, name=screen: app.show(name)); grid.add_widget(button)
        self.body.add_widget(grid)
        self.body.add_widget(Widget())
        refresh = PTvButton(text="REFRESH LIVE STATUS", background_color=ACCENT)
        refresh.bind(on_release=lambda *_: self.load()); self.body.add_widget(refresh)

    def load(self):
        self.app_ref.ensure_token(lambda: self.app_ref.call("GET", "/api/v1/dashboard", self.update))

    def update(self, data, error):
        if error:
            self.live_title.text, self.live_title.color = "● OFFLINE / RETRY", ORANGE
            self.live_detail.text = str(error); return
        self.live_title.text, self.live_title.color = "● LIVE  •  FASTAPI 2.0", GREEN
        summary = data.get("summary", {})
        self.live_detail.text = f"{self.app_ref.api.server}\nDevices {summary.get('devices', 0)}  •  Keys {summary.get('tokens', 0)}  •  Events {summary.get('logs', 0)}"


class KeyScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "API Key", name="key", **kwargs)
        self.output = Label(text="Your PTv user key is generated automatically.", color=TEXT, halign="left", valign="top", font_size=sp(13), size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.output); self.body.add_widget(scroll)
        create = PTvButton(text="GENERATE / ROTATE API KEY", background_color=ACCENT)
        create.bind(on_release=lambda *_: app.provision("python", self.render)); self.body.add_widget(create)
        copy = PTvButton(text="COPY CURRENT KEY")
        copy.bind(on_release=lambda *_: self.copy_key()); self.body.add_widget(copy)

    def load(self): self.show_key()

    def show_key(self):
        key = self.app_ref.api.token
        self.output.text = ("[b]CURRENT KEY[/b]\n" + key) if key else "No key yet. Tap Generate."
        self.output.markup = True; self.output.texture_update(); self.output.height = max(dp(120), self.output.texture_size[1] + dp(20))

    def copy_key(self):
        if self.app_ref.api.token: Clipboard.copy(self.app_ref.api.token); self.app_ref.dialog("Copied", "API key copied to clipboard")
        else: self.app_ref.dialog("No key", "Generate a key first")

    def render(self, data, error):
        if error: self.app_ref.dialog("Key error", error)
        self.show_key()


class DatabaseScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Database", name="database", **kwargs)
        self.output = Label(text="Loading tables...", color=TEXT, halign="left", valign="top", font_size=sp(13), size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.output); self.body.add_widget(scroll)
        create = PTvButton(text="CREATE TABLE", background_color=ACCENT); create.bind(on_release=lambda *_: self.create_dialog()); self.body.add_widget(create)
        refresh = PTvButton(text="REFRESH TABLES"); refresh.bind(on_release=lambda *_: self.load()); self.body.add_widget(refresh)

    def load(self): self.app_ref.ensure_token(lambda: self.app_ref.call("GET", "/api/v1/database/tables", self.render))

    def render(self, data, error):
        self.output.text = str(error) if error else "[b]TABLES[/b]\n\n" + "\n".join(f"● {x['name']}  ({x['type']})" for x in data.get("tables", []))
        self.output.markup = not bool(error); self.output.texture_update(); self.output.height = max(dp(160), self.output.texture_size[1] + dp(20))

    def create_dialog(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        name = TextInput(hint_text="table name e.g. users", multiline=False, font_size=sp(14), size_hint_y=None, height=dp(44))
        columns = TextInput(text="id INTEGER PRIMARY KEY, name TEXT, created_at TEXT", multiline=True, font_size=sp(13), size_hint_y=None, height=dp(105))
        box.add_widget(Label(text="Table name", color=MUTED, size_hint_y=None, height=dp(25))); box.add_widget(name)
        box.add_widget(Label(text="Columns SQL", color=MUTED, size_hint_y=None, height=dp(25))); box.add_widget(columns)
        run = PTvButton(text="CREATE", background_color=ACCENT); box.add_widget(run)
        popup = Popup(title="Create table", content=box, size_hint=(0.92, 0.72))
        run.bind(on_release=lambda *_: (popup.dismiss(), self.app_ref.sql(f"CREATE TABLE {name.text.strip()} ({columns.text.strip()})", self.render)))
        popup.open()


class SupabaseScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "Supabase", name="supabase", **kwargs)
        self.output = Label(text="Checking services...", color=TEXT, halign="left", valign="top", font_size=sp(13), size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.output); self.body.add_widget(scroll)
        key = PTvButton(text="GENERATE SUPABASE API KEY", background_color=ACCENT); key.bind(on_release=lambda *_: app.provision("supabase", self.render_key)); self.body.add_widget(key)
        copy = PTvButton(text="COPY SUPABASE KEY"); copy.bind(on_release=lambda *_: self.copy()); self.body.add_widget(copy)

    def load(self):
        self.app_ref.ensure_token(lambda: self.app_ref.call("GET", "/api/v1/services", self.render_services))

    def render_services(self, data, error):
        if error: self.output.text = str(error); return
        lines = ["[b]LIVE INTEGRATIONS[/b]", ""]
        for name, info in data.get("services", {}).items():
            if isinstance(info, dict): lines.append(f"● {name.upper()} — {info.get('status')}\n   Database: {'READY' if info.get('database') else 'OFF'}   Storage: {'READY' if info.get('storage') else 'OFF'}")
        self.output.text = "\n".join(lines); self.output.markup = True; self.output.texture_update(); self.output.height = dp(230)

    def render_key(self, data, error):
        if error: self.app_ref.dialog("Supabase key error", error)
        else: self.app_ref.dialog("Supabase API key", data.get("token", "")); self.render_services(data, None)

    def copy(self):
        if self.app_ref.api.token: Clipboard.copy(self.app_ref.api.token); self.app_ref.dialog("Copied", "Current key copied")


class SQLScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, "SQL Editor", name="sql", **kwargs)
        self.editor = TextInput(text="CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT);", multiline=True, font_size=sp(13), background_color=PANEL_2, foreground_color=TEXT, hint_text_color=MUTED, size_hint_y=None, height=dp(145))
        self.body.add_widget(self.editor)
        run = PTvButton(text="RUN SQL", background_color=ACCENT); run.bind(on_release=lambda *_: self.run_sql()); self.body.add_widget(run)
        self.result = Label(text="One statement at a time. CREATE, SELECT, INSERT, UPDATE, DELETE and ALTER are supported.", color=MUTED, halign="left", valign="top", font_size=sp(12), size_hint_y=None, text_size=(None, None))
        scroll = ScrollView(); scroll.add_widget(self.result); self.body.add_widget(scroll)

    def run_sql(self): self.app_ref.ensure_token(lambda: self.app_ref.sql(self.editor.text, self.show))

    def show(self, data, error):
        self.result.text = str(error) if error else json.dumps(data, indent=2, ensure_ascii=False)
        self.result.texture_update(); self.result.height = max(dp(180), self.result.texture_size[1] + dp(20))


class PTvApp(App):
    title = APP_NAME

    def __init__(self, **kwargs):
        super().__init__(**kwargs); self.api = CloudAPI(); self.device_id = str(uuid.uuid4()); self.store = JsonStore("ptv_settings.json"); self.screens = {}

    def build(self):
        Window.clearcolor = BG
        saved = self.store.get("connection") if self.store.exists("connection") else {}
        self.api.configure(saved.get("server", DEFAULT_SERVER), saved.get("token", ""))
        root = BoxLayout(orientation="vertical"); self.manager = ScreenManager(transition=SlideTransition(duration=0.12))
        screens = [HomeScreen(self), KeyScreen(self), DatabaseScreen(self), SupabaseScreen(self), SQLScreen(self)]
        for screen in screens: self.screens[screen.name] = screen; self.manager.add_widget(screen)
        root.add_widget(self.manager)
        nav = GridLayout(cols=4, size_hint_y=None, height=dp(52), spacing=dp(3), padding=dp(3))
        for text, name in (("HOME", "home"), ("API KEY", "key"), ("DATABASE", "database"), ("SQL", "sql")):
            b = PTvButton(text=text, height=dp(48), font_size=sp(10)); b.bind(on_release=lambda _, target=name: self.show(target)); nav.add_widget(b)
        root.add_widget(nav); Clock.schedule_once(lambda *_: self.screens["home"].load(), 0.5); return root

    def show(self, name):
        self.manager.current = name
        self.screens[name].load()

    def configure(self, server):
        self.api.configure(server, self.api.token); self.store.put("connection", server=self.api.server, token=self.api.token)

    def provision(self, token_type, callback):
        payload = {"device_id": self.device_id, "device_name": "PTv Mobile", "platform": "Android", "app_version": APP_VERSION, "token_type": token_type}
        self.call("POST", "/api/v1/provision", lambda data, error: self._provisioned(data, error, callback), payload=payload, empty_ok=True)

    def _provisioned(self, data, error, callback):
        if not error and data.get("token"):
            self.api.token = data["token"]; self.store.put("connection", server=self.api.server, token=self.api.token)
        callback(data, error)

    def ensure_token(self, callback):
        callback() if self.api.token else self.provision("python", lambda _data, error: callback() if not error else self.dialog("Connection error", error))

    def sql(self, text, callback): self.call("POST", "/api/v1/sql", callback, {"sql": text})

    def call(self, method, endpoint, callback=None, payload=None, empty_ok=False):
        def worker():
            try: value, error = self.api.request(method, endpoint, payload), None
            except Exception as exc: value, error = None, exc
            Clock.schedule_once(lambda _dt: callback(value, error) if callback else None, 0)
        threading.Thread(target=worker, daemon=True).start()

    def dialog(self, title, message):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        text = Label(text=str(message), color=TEXT, halign="left", valign="top", font_size=sp(13))
        text.bind(size=fit); box.add_widget(text)
        close = PTvButton(text="CLOSE"); box.add_widget(close)
        popup = Popup(title=title, content=box, size_hint=(0.9, 0.55)); close.bind(on_release=popup.dismiss); popup.open()


if __name__ == "__main__":
    PTvApp().run()
