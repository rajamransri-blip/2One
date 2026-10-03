"""Visible parent dashboard. All actions require authenticated, consent-paired accounts."""
import os
import threading
import webbrowser
from datetime import datetime
from functools import partial
from pathlib import Path

from kivy.clock import Clock
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
from api.client import APIError, Client, SocketFeed


class ParentApp(MDApp):
    def build(self):
        self.title = "Safety • Parent"
        self.theme_cls.primary_palette = "Blue"
        self.client = Client(self.user_data_dir)
        self.feed = None
        self.selected = None
        self.root_box = MDBoxLayout(orientation="vertical", padding="12dp", spacing="9dp")
        self.show_login()
        return self.root_box

    def clear(self, title):
        self.root_box.clear_widgets()
        self.label(self.root_box, title, 24, 48)
        self.scroller = ScrollView()
        self.content = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing="10dp", padding="6dp")
        self.scroller.add_widget(self.content)
        self.root_box.add_widget(self.scroller)
        self.notice = MDLabel(text="", size_hint_y=None, height="50dp", theme_text_color="Secondary")
        self.root_box.add_widget(self.notice)

    def label(self, container, text, size=16, height=46):
        item = MDLabel(text=str(text), font_style="H5" if size >= 24 else "Body1", adaptive_height=False,
                       size_hint_y=None, height=f"{height}dp", halign="left")
        container.add_widget(item)
        return item

    def field(self, hint, password=False, value=""):
        item = MDTextField(hint_text=hint, text=str(value), password=password, size_hint_y=None, height="55dp")
        self.content.add_widget(item)
        return item

    def button(self, title, callback, flat=False):
        widget = MDFlatButton(text=title, size_hint_y=None, height="48dp") if flat else MDRaisedButton(text=title, size_hint_y=None, height="48dp")
        widget.bind(on_release=lambda unused: callback())
        self.content.add_widget(widget)
        return widget

    def message(self, text):
        self.notice.text = str(text)

    def run_api(self, operation, success=None):
        def worker():
            try:
                answer = operation()
            except (APIError, ValueError, KeyError) as error:
                Clock.schedule_once(lambda dt: self.message(error))
            else:
                if success:
                    Clock.schedule_once(lambda dt: success(answer))
        threading.Thread(target=worker, daemon=True).start()

    def show_login(self):
        self.clear("Family Safety • Parent")
        self.label(self.content, "Sign in to your parent account. Pairing requires the child's visible acceptance.", 16, 84)
        email = self.field("Email")
        password = self.field("Password (12+ characters)", password=True)

        def login():
            self.run_api(lambda: self.client.login(email.text.strip(), password.text, "parent"), self.logged_in)

        self.button("Login", login)
        self.button("Create parent account", lambda: self.run_api(
            lambda: self.client.register(email.text.strip(), password.text, "parent"),
            lambda response: self.message(response.get("message", "Account created; login now"))), flat=True)
        self.button("Forgot password", lambda: self.run_api(
            lambda: self.client._send("POST", "/auth/forgot-password", {"email": email.text.strip()}),
            lambda response: self.message(response["message"])), flat=True)
        self.button("Server / Settings", self.show_settings, flat=True)

    def logged_in(self, response):
        self.feed = SocketFeed(self.client, lambda frame: Clock.schedule_once(lambda dt: self.on_event(frame)))
        self.feed.start()
        self.show_dashboard()

    def on_event(self, frame):
        if frame.get("type") in ("sos", "checkin_response", "geofence_exit", "geofence_enter", "message", "status", "paired", "revoked"):
            self.message("Update: " + frame["type"].replace("_", " "))
            if self.selected is None:
                self.load_children()

    def show_dashboard(self):
        self.selected = None
        self.clear("Parent dashboard")
        self.label(self.content, "Location sharing is voluntary. Coordinates are approximate, not a substitute for emergency services.", 16, 75)
        self.button("Refresh children", self.load_children)
        self.button("Create one-time pairing code + QR", self.create_pairing)
        self.button("Alerts & notifications", self.show_notifications)
        self.button("Settings", self.show_settings, flat=True)
        self.children_panel = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing="8dp")
        self.content.add_widget(self.children_panel)
        self.load_children()
        Clock.schedule_once(lambda dt: self.poll_dashboard(), 20)

    def poll_dashboard(self):
        if self.client.access and self.selected is None:
            self.load_children()
            Clock.schedule_once(lambda dt: self.poll_dashboard(), 20)

    def load_children(self):
        def display(rows):
            if self.selected is not None:
                return
            self.children_panel.clear_widgets()
            if not rows:
                self.label(self.children_panel, "No children paired yet. Create a short-lived code to share in person.", 16, 80)
            for child in rows:
                status = child["status"]
                battery = status["battery"] if status["battery"] is not None else "?"
                latest = child["last_location"]
                last = latest["recorded_at"] if latest else "Not shared"
                checkin = child["last_checkin"]
                summary = (f"{child['device_name']} • {child['email']}\n"
                           f"{'ONLINE' if status['online'] else 'OFFLINE'} • battery {battery}% • network {status['network']}\n"
                           f"Sharing {'ON' if status['sharing'] else 'OFF'} • last location {last}\n"
                           f"Check-in {checkin['response'] if checkin else 'none'} • ACTIVE SOS: {len(child['active_sos'])}")
                self.label(self.children_panel, summary, 16, 130)
                button = MDRaisedButton(text="Open child", size_hint_y=None, height="48dp")
                button.bind(on_release=lambda unused, cid=child["id"]: self.show_child(cid))
                self.children_panel.add_widget(button)
        self.run_api(lambda: self.client.request("GET", "/children"), display)

    def create_pairing(self):
        def show(data):
            self.clear("Pairing code")
            self.label(self.content, "Share only with the child in person; it expires and works once.", 16, 66)
            self.label(self.content, data["code"], 24, 55)
            self.label(self.content, "Expires: " + data["expires_at"], 16, 55)
            try:
                import qrcode
                path = os.path.join(self.user_data_dir, "pair_qr.png")
                qrcode.make(data["qr_payload"]).save(path)
                self.content.add_widget(Image(source=path, size_hint_y=None, height="260dp"))
            except (ImportError, OSError):
                self.label(self.content, "QR unavailable; type the code into the child app.", 16, 50)
            self.button("Back", self.show_dashboard)
        self.run_api(lambda: self.client.request("POST", "/devices/pairing-codes"), show)

    def show_child(self, child_id):
        self.selected = child_id
        self.clear("Child safety")
        self.button("← Dashboard", self.show_dashboard, flat=True)
        self.button("View location on map", self.show_location)
        self.button("Location history", self.show_history)
        self.button("Safety zones", self.show_zones)
        self.button("Request check-in", self.request_checkin)
        self.button("Check-in responses", self.show_checkins)
        self.button("Messages", self.show_messages)
        self.button("Emergency / SOS history", self.show_sos)
        self.button("Device status", self.show_device)
        self.button("Revoke pairing", self.confirm_revoke, flat=True)

    def child_page(self, title):
        self.clear(title)
        self.button("← Child", lambda: self.show_child(self.selected), flat=True)

    def show_location(self):
        self.child_page("Last shared location")
        def display(point):
            self.label(self.content, f"{point['latitude']}, {point['longitude']}\n±{point['accuracy']}m • {point['recorded_at']}", 16, 92)
            self.button("Open map app", lambda: webbrowser.open(
                f"https://www.openstreetmap.org/?mlat={point['latitude']}&mlon={point['longitude']}#map=16/{point['latitude']}/{point['longitude']}"))
        self.run_api(lambda: self.client.request("GET", "/location/latest/" + self.selected), display)

    def show_history(self):
        self.child_page("Location history (retention limited)")
        self.run_api(lambda: self.client.request("GET", "/location/history/" + self.selected),
                     lambda points: [self.label(self.content, f"{p['recorded_at']}\n{p['latitude']:.5f}, {p['longitude']:.5f} ±{p['accuracy']}m", 16, 66) for p in points])

    def show_device(self):
        self.child_page("Device status")
        self.run_api(lambda: self.client.request("GET", "/device/status/" + self.selected),
                     lambda data: self.label(self.content, "\n".join(f"{k}: {v}" for k, v in data.items()), 16, 260))

    def show_zones(self):
        self.child_page("Safety zones • approximate")
        name, latitude, longitude, radius = self.field("Zone name"), self.field("Latitude"), self.field("Longitude"), self.field("Radius in meters (50–50000)", value="300")
        def add():
            try:
                data = {"child_id": self.selected, "name": name.text, "latitude": float(latitude.text),
                        "longitude": float(longitude.text), "radius_m": int(radius.text)}
            except ValueError:
                self.message("Enter numeric coordinates and radius")
                return
            self.run_api(lambda: self.client.request("POST", "/geofences", data), lambda result: self.show_zones())
        self.button("Create zone", add)
        def display(zones):
            for zone in zones:
                self.label(self.content, f"{zone['name']} • radius {zone['radius_m']}m • inside {zone['inside']}", 16, 60)
                self.button("Delete " + zone["name"], lambda zid=zone["id"]: self.run_api(
                    lambda: self.client.request("DELETE", "/geofences/" + zid), lambda result: self.show_zones()), flat=True)
        self.run_api(lambda: self.client.request("GET", "/geofences?child_id=" + self.selected), display)

    def request_checkin(self):
        self.run_api(lambda: self.client.request("POST", "/checkins/request", {"child_id": self.selected, "reminder_minutes": 15}),
                     lambda result: self.message("Check-in requested; due " + result["deadline"]))

    def show_checkins(self):
        self.child_page("Check-ins")
        self.run_api(lambda: self.client.request("GET", "/checkins/" + self.selected),
                     lambda items: [self.label(self.content, f"{i['created_at']} • {i['response'] or 'Awaiting response'}", 16, 58) for i in items])

    def show_messages(self):
        self.child_page("Messages")
        text = self.field("Message child (max 2000 characters)")
        self.button("Send", lambda: self.run_api(lambda: self.client.request("POST", "/messages", {
            "child_id": self.selected, "body": text.text}), lambda result: self.show_messages()))
        def display(items):
            for item in reversed(items):
                self.label(self.content, f"{item['created_at']} • {item['body'] or 'Media'}\nRead: {item['read_at'] or 'not yet'}", 16, 75)
                if item["sender_id"] != self.client.user_id and not item["read_at"]:
                    self.run_api(lambda mid=item["id"]: self.client.request("POST", f"/messages/{mid}/read"))
        self.run_api(lambda: self.client.request("GET", "/messages/" + self.selected), display)

    def show_sos(self):
        self.child_page("Emergency alerts")
        def display(items):
            for item in items:
                self.label(self.content, f"{'ACTIVE SOS' if not item['acknowledged_at'] else 'Acknowledged'} • {item['created_at']}\n"
                             f"Last known: {item['latitude']}, {item['longitude']} • battery {item['battery']}", 16, 83)
                if not item["acknowledged_at"]:
                    self.button("Acknowledge SOS", lambda sid=item["id"]: self.run_api(
                        lambda: self.client.request("POST", f"/sos/{sid}/acknowledge"), lambda result: self.show_sos()))
        self.run_api(lambda: self.client.request("GET", "/sos/" + self.selected), display)

    def show_notifications(self):
        self.clear("Alerts & notifications")
        self.button("← Dashboard", self.show_dashboard, flat=True)
        self.run_api(lambda: self.client.request("GET", "/notifications"), lambda items: [
            self.label(self.content, f"{i['created_at']} • {i['kind']}\n{i['detail']}", 16, 70) for i in items])

    def confirm_revoke(self):
        self.child_page("Confirm revocation")
        self.label(self.content, "Revoking immediately stops this parent's access and disables sharing. Re-pairing requires a new code.", 16, 100)
        self.button("Confirm revoke", lambda: self.run_api(
            lambda: self.client.request("POST", "/devices/revoke", {"child_id": self.selected}),
            lambda result: self.show_dashboard()))

    def show_settings(self):
        self.clear("Settings")
        self.label(self.content, "Use HTTPS for public servers; HTTP works only on private LAN/emulator. Tokens are memory-only.", 16, 93)
        url = self.field("SERVER_URL", value=self.client.base)
        def save():
            try:
                self.client.set_url(url.text)
            except APIError as error:
                self.message(error)
            else:
                self.message("Server address saved. Log in again.")
        self.button("Save server address", save)
        self.button("Log out", lambda: self.run_api(self.client.logout, lambda answer: self.show_login()))
        self.button("Back", self.show_dashboard if self.client.access else self.show_login, flat=True)

    def on_stop(self):
        if self.feed:
            self.feed.stop()


if __name__ == "__main__":
    ParentApp().run()
