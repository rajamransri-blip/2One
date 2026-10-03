"""Child-visible safety app: no covert sensors, no automatic camera or microphone access."""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
from api.client import APIError, Client, SocketFeed


class ChildApp(MDApp):
    def build(self):
        self.title = "Safety • Child"
        self.theme_cls.primary_palette = "Teal"
        self.client = Client(self.user_data_dir)
        self.feed = None
        self.sharing = False
        self.recording = None
        self.countdown = None
        self.root_box = MDBoxLayout(orientation="vertical", padding="12dp", spacing="9dp")
        self.show_login()
        return self.root_box

    def clear(self, title):
        self.root_box.clear_widgets()
        self.heading = MDLabel(text=title, font_style="H5", size_hint_y=None, height="52dp")
        self.root_box.add_widget(self.heading)
        scroll = ScrollView()
        self.content = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing="10dp", padding="6dp")
        scroll.add_widget(self.content)
        self.root_box.add_widget(scroll)
        self.notice = MDLabel(text="", size_hint_y=None, height="52dp", theme_text_color="Secondary")
        self.root_box.add_widget(self.notice)

    def label(self, text, height=56):
        item = MDLabel(text=str(text), size_hint_y=None, height=f"{height}dp")
        self.content.add_widget(item)
        return item

    def field(self, hint, password=False, value=""):
        item = MDTextField(hint_text=hint, text=str(value), password=password, size_hint_y=None, height="55dp")
        self.content.add_widget(item)
        return item

    def button(self, title, action, flat=False):
        item = MDFlatButton(text=title, size_hint_y=None, height="48dp") if flat else MDRaisedButton(text=title, size_hint_y=None, height="48dp")
        item.bind(on_release=lambda unused: action())
        self.content.add_widget(item)
        return item

    def message(self, value):
        self.notice.text = str(value)

    def run_api(self, operation, success=None):
        def worker():
            try:
                result = operation()
            except (APIError, ValueError, KeyError, OSError) as error:
                Clock.schedule_once(lambda dt: self.message(error))
            else:
                if success:
                    Clock.schedule_once(lambda dt: success(result))
        threading.Thread(target=worker, daemon=True).start()

    def show_login(self):
        self.clear("Family Safety • Child")
        self.label("This app visibly shares your location only when you switch sharing on. You can stop it or unpair.", 95)
        email, password = self.field("Email"), self.field("Password (12+ characters)", password=True)
        self.button("Login", lambda: self.run_api(
            lambda: self.client.login(email.text.strip(), password.text, "child"), lambda response: self.logged_in()))
        self.button("Create child account", lambda: self.run_api(
            lambda: self.client.register(email.text.strip(), password.text, "child"),
            lambda response: self.message(response.get("message", "Account created; login now"))), flat=True)
        self.button("Server / Settings", self.show_settings, flat=True)

    def logged_in(self):
        self.feed = SocketFeed(self.client, lambda event: Clock.schedule_once(lambda dt: self.on_event(event)))
        self.feed.start()
        self.show_home()

    def on_event(self, event):
        kind = event.get("type")
        if kind in ("message", "checkin_request", "revoked", "sos_acknowledged"):
            self.message("Safety update: " + kind.replace("_", " "))
            self.notify("Family Safety", "A safety update is waiting in the app")
            if kind == "revoked":
                self.stop_sharing()
            if kind == "checkin_request":
                self.show_checkins()

    def notify(self, title, detail):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            context = autoclass("android.content.Context")
            manager = activity.getSystemService(context.NOTIFICATION_SERVICE)
            build = autoclass("android.os.Build$VERSION")
            if build.SDK_INT >= 26:
                channel = autoclass("android.app.NotificationChannel")("safety_events", "Family safety events", 4)
                manager.createNotificationChannel(channel)
                notification = autoclass("android.app.Notification$Builder")(activity, "safety_events")
            else:
                notification = autoclass("android.app.Notification$Builder")(activity)
            result = (notification.setSmallIcon(activity.getApplicationInfo().icon).setContentTitle(title)
                      .setContentText(detail).setAutoCancel(True).build())
            manager.notify(1438, result)
        except Exception as error:
            self.message("Open the app to read safety updates; notifications unavailable")

    def show_home(self):
        self.clear("Child safety home")
        self.parent_label = self.label("Parent account: checking pairing…", 66)
        self.status_label = self.label("Safety status: checking connection…", 80)
        self.button("Pair with parent (one-time code)", self.show_pairing)
        self.button("Start / stop visible location sharing", self.toggle_sharing)
        self.button("SOS • emergency", self.start_sos)
        self.button("Check-in responses", self.show_checkins)
        self.button("Message parent", self.show_messages)
        self.button("Take photo and send", self.take_photo)
        self.button("Start voice recording", self.start_recording)
        self.button("Stop recording and send", self.stop_recording)
        self.button("Enable safety notifications", self.enable_notifications, flat=True)
        self.button("Settings / Unpair", self.show_settings, flat=True)
        self.refresh_home()
        Clock.schedule_once(lambda dt: self.home_poll(), 30)

    def home_poll(self):
        if self.client.access and self.heading.text == "Child safety home":
            self.refresh_home()
            Clock.schedule_once(lambda dt: self.home_poll(), 30)

    def refresh_home(self):
        def display_parents(items):
            self.parent_label.text = "Paired parent: " + (", ".join(i["email"] for i in items) if items else "none — pairing needed")
        self.run_api(lambda: self.client.request("GET", "/parents"), display_parents)
        def display_status(data):
            self.sharing = data["sharing"]
            self.status_label.text = (f"Connection: {'ONLINE' if data['online'] else 'OFFLINE'} • battery {data['battery']}%\n"
                                      f"Location sharing: {'ACTIVE • visible service' if data['sharing'] else 'OFF'} • network {data['network']}")
        self.run_api(lambda: self.client.request("GET", "/device/status/" + self.client.user_id), display_status)

    def show_pairing(self):
        self.clear("Consent-based pairing")
        self.label("Only enter the code a trusted parent shows you. You may unpair any time. Location stays OFF after pairing.", 100)
        code = self.field("8-character pairing code")
        device = self.field("Device name", value="My phone")
        self.button("Pair this device", lambda: self.run_api(
            lambda: self.client.request("POST", "/devices/pair", {"code": code.text.upper().strip(), "device_name": device.text}),
            lambda result: self.show_home()))
        self.button("Back", self.show_home, flat=True)

    def permission(self, names, explanation, granted):
        if platform != "android":
            self.message("Android permissions are unavailable on this platform")
            return
        self.message(explanation)
        from android.permissions import check_permission, request_permissions
        required = [name for name in names if not check_permission(name)]
        if not required:
            granted()
            return
        request_permissions(required, lambda permissions, results: Clock.schedule_once(
            lambda dt: granted() if all(results) else self.message("Permission denied; feature remains off")))

    def enable_notifications(self):
        if platform != "android":
            self.message("Notification permission is only available on Android")
            return
        from jnius import autoclass
        if autoclass("android.os.Build$VERSION").SDK_INT < 33:
            self.message("Notifications are available in Android settings")
            return
        self.permission(["android.permission.POST_NOTIFICATIONS"],
                        "Allow notifications to receive family safety requests while the app is open?", lambda: self.message("Notifications enabled"))

    def toggle_sharing(self):
        if self.sharing:
            self.stop_sharing()
        else:
            self.label("Turning on location starts a foreground Android service with a persistent notification. Switch off here anytime.", 90)
            self.permission(["android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"],
                            "Location is sent only to your paired parent while the visible sharing service runs.", self.start_sharing)

    def start_sharing(self):
        if platform != "android":
            self.message("Automatic foreground location sharing requires Android")
            return
        def start(tokens):
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                service = autoclass("org.consentsafety.safekid.ServiceLocation")
                argument = json.dumps({"url": self.client.base, "access": tokens["access_token"], "refresh": tokens["refresh_token"],
                                       "child_id": self.client.user_id, "interval": 90})
                service.start(activity, "ic_launcher", "Location sharing ACTIVE", "Tap to open Family Safety; stop sharing in app", argument)
            except Exception as error:
                self.run_api(lambda: self.client.request("POST", "/device/status", {"sharing": False, "online": True}),
                             lambda result: self.message("Could not start visible service; location sharing OFF"))
                return
            self.sharing = True
            self.show_home()
        def create_location_session():
            self.client.request("POST", "/device/status", {
                "sharing": True, "online": True, "location_enabled": True, "notifications_enabled": True})
            return self.client.request("POST", "/auth/location-session")
        self.run_api(create_location_session, start)

    def stop_sharing(self):
        if platform == "android":
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                autoclass("org.consentsafety.safekid.ServiceLocation").stop(activity)
            except Exception as error:
                self.message("Could not stop service; check Android running services")
        self.sharing = False
        self.run_api(lambda: self.client.request("POST", "/device/status", {"sharing": False, "online": True}),
                     lambda result: self.show_home())

    def start_sos(self):
        self.clear("SOS • confirm emergency")
        self.label("An SOS will tell your paired parent you need help and send last known location. Call local emergency services for immediate danger.", 125)
        self.seconds = max(3, min(15, int(os.getenv("SOS_CANCEL_SECONDS", "5"))))
        button = self.button(f"Sending SOS in {self.seconds}s — tap to cancel", self.cancel_sos)
        def tick(dt):
            self.seconds -= 1
            if self.seconds <= 0:
                self.countdown = None
                self.run_api(lambda: self.client.request("POST", "/sos"),
                             lambda result: self.show_sos_result(result))
                return False
            button.text = f"Sending SOS in {self.seconds}s — tap to cancel"
            return True
        self.countdown = Clock.schedule_interval(tick, 1)

    def cancel_sos(self):
        if self.countdown:
            self.countdown.cancel()
            self.countdown = None
        self.show_home()
        self.message("SOS cancelled before sending")

    def show_sos_result(self, result):
        self.show_home()
        self.message("SOS sent to your parent at " + result["created_at"])

    def show_checkins(self):
        self.clear("Check-ins")
        self.button("← Home", self.show_home, flat=True)
        def display(items):
            if not items:
                self.label("No check-in requests")
            for item in items:
                self.label("Parent requested a safety check-in • " + item["created_at"] + "\nResponse: " + (item["response"] or "pending"), 80)
                if not item["response"]:
                    for text, choice in (("I'm Safe", "safe"), ("Need Help", "help")):
                        self.button(text, lambda cid=item["id"], result=choice: self.run_api(
                            lambda: self.client.request("POST", "/checkins/respond", {"checkin_id": cid, "response": result}),
                            lambda response: self.show_checkins()))
        self.run_api(lambda: self.client.request("GET", "/checkins/" + self.client.user_id), display)

    def show_messages(self):
        self.clear("Messages with parent")
        self.button("← Home", self.show_home, flat=True)
        text = self.field("Write message")
        self.button("Send message", lambda: self.run_api(lambda: self.client.request("POST", "/messages", {
            "child_id": self.client.user_id, "body": text.text}), lambda response: self.show_messages()))
        def display(items):
            for item in reversed(items):
                self.label(f"{item['created_at']} • {item['body'] or 'Media attached'}\nRead: {item['read_at'] or 'not yet'}", 80)
                if item["sender_id"] != self.client.user_id and not item["read_at"]:
                    self.run_api(lambda mid=item["id"]: self.client.request("POST", f"/messages/{mid}/read"))
        self.run_api(lambda: self.client.request("GET", "/messages/" + self.client.user_id), display)

    def send_media(self, kind, path, mime):
        def operation():
            try:
                with open(path, "rb") as source:
                    raw = source.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise APIError("Media larger than 5 MiB; choose a smaller file")
                item = self.client.upload(kind, raw, mime, os.path.basename(path))
                return self.client.request("POST", "/messages", {"child_id": self.client.user_id, "media_id": item["id"]})
            finally:
                if os.path.exists(path):
                    os.unlink(path)  # never retain sensitive media after the user action
        self.run_api(operation, lambda answer: self.message(kind.title() + " shared with parent"))

    def take_photo(self):
        self.permission(["android.permission.CAMERA"],
                        "The camera opens only when you tap Take photo; sharing requires another visible action.", self.open_camera)

    def open_camera(self):
        from plyer import camera
        path = os.path.join(self.user_data_dir, "photo_" + uuid4().hex + ".jpg")
        try:
            camera.take_picture(filename=path, on_complete=lambda filename: Clock.schedule_once(
                lambda dt: self.confirm_photo(filename)))
        except Exception as error:
            self.message("Camera unavailable; no photo was shared")

    def confirm_photo(self, path):
        if not path or not os.path.exists(path):
            self.message("Photo cancelled")
            return
        self.clear("Share this photo?")
        self.label("This photo was taken by you. Sharing sends it only to your paired parent. Cancel deletes it.", 95)
        self.button("Send photo", lambda: self.send_media("photo", path, "image/jpeg"))
        self.button("Cancel and delete", lambda: (os.unlink(path), self.show_home()), flat=True)

    def start_recording(self):
        self.permission(["android.permission.RECORD_AUDIO"],
                        "Microphone is used only after you press Start voice recording; press Stop and Send to share.", self.record_voice)

    def record_voice(self):
        if self.recording:
            self.message("Already recording")
            return
        try:
            from jnius import autoclass
            recorder = autoclass("android.media.MediaRecorder")()
            path = os.path.join(self.user_data_dir, "voice_" + uuid4().hex + ".m4a")
            recorder.setAudioSource(1)
            recorder.setOutputFormat(2)
            recorder.setAudioEncoder(3)
            recorder.setOutputFile(path)
            recorder.prepare()
            recorder.start()
            self.recording = (recorder, path)
            self.message("MICROPHONE ACTIVE — tap Stop recording and send")
        except Exception as error:
            self.message("Microphone unavailable; nothing recorded")

    def stop_recording(self):
        if not self.recording:
            self.message("No voice recording in progress")
            return
        recorder, path = self.recording
        self.recording = None
        try:
            recorder.stop()
            recorder.release()
            self.clear("Share this voice message?")
            self.label("The microphone is off. Share the recording or delete it.", 80)
            self.button("Send voice message", lambda: self.send_media("voice", path, "audio/mp4"))
            self.button("Delete recording", lambda: (os.unlink(path), self.show_home()), flat=True)
        except Exception as error:
            recorder.release()
            if os.path.exists(path):
                os.unlink(path)
            self.message("Recording failed; file deleted")

    def show_settings(self):
        self.clear("Settings & consent")
        self.label("Sharing uses a visible Android foreground service and can be stopped here anytime. Public servers require HTTPS.", 92)
        url = self.field("SERVER_URL", value=self.client.base)
        def save():
            try:
                self.client.set_url(url.text)
                self.message("Server URL saved; sign in again")
            except APIError as error:
                self.message(error)
        self.button("Save server URL", save)
        self.button("Stop sharing", self.stop_sharing)
        self.button("Unpair my device", lambda: self.run_api(lambda: self.client.request(
            "POST", "/devices/revoke", {"child_id": self.client.user_id}), lambda result: self.show_home()))
        self.button("Log out", self.logout)
        self.button("Back", self.show_home if self.client.access else self.show_login, flat=True)

    def logout(self):
        if self.sharing:
            self.stop_sharing()
        if self.feed:
            self.feed.stop()
        self.run_api(self.client.logout, lambda answer: self.show_login())

    def on_stop(self):
        if self.feed:
            self.feed.stop()
        # Visible foreground service continues only when the child explicitly enabled sharing.


if __name__ == "__main__":
    ChildApp().run()
