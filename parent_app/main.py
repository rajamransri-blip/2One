"""Lightweight, startup-safe Parent controller for the consent safety backend."""
import threading
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from api.client import APIError, Client

BG = (0.035, 0.047, 0.075, 1); PANEL = (0.09, 0.13, 0.21, 1); BLUE = (0.28, 0.62, 1, 1); TEXT = (0.92, 0.95, 1, 1); MUTED = (0.60, 0.67, 0.78, 1)

class ParentApp(App):
    def build(self):
        self.title = "Family Safety Parent"; self.client = Client(self.user_data_dir); self.root_box = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8)); self.root_box.canvas.before.clear(); self.show_login(); return self.root_box
    def label(self, text, size=16, color=TEXT, height=None):
        w=Label(text=str(text), color=color, font_size=sp(size), halign="left", valign="middle", size_hint_y=None, height=dp(height or max(42, size*2.2))); w.bind(size=lambda x,_: setattr(x,"text_size",(x.width-dp(12),None))); return w
    def input(self, hint, password=False, value=""):
        w=TextInput(hint_text=hint, text=value, password=password, multiline=False, size_hint_y=None, height=dp(48), font_size=sp(14), foreground_color=TEXT, hint_text_color=MUTED, background_color=PANEL, padding=[dp(12),dp(12)]); return w
    def button(self, text, fn, color=PANEL):
        w=Button(text=text, size_hint_y=None, height=dp(48), font_size=sp(13), color=TEXT, background_normal="", background_color=color); w.bind(on_release=lambda *_: fn()); return w
    def clear(self, title):
        self.root_box.clear_widgets(); self.root_box.add_widget(self.label(title,22,height=54)); self.scroll=ScrollView(); self.content=BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(4), size_hint_y=None); self.content.bind(minimum_height=self.content.setter("height")); self.scroll.add_widget(self.content); self.root_box.add_widget(self.scroll); self.notice=self.label("",13,MUTED,44); self.root_box.add_widget(self.notice)
    def message(self, text): Clock.schedule_once(lambda *_: setattr(self.notice,"text",str(text)),0)
    def api(self, operation, success):
        def work():
            try: result=operation(); Clock.schedule_once(lambda *_: success(result),0)
            except (APIError, ValueError, KeyError) as e: self.message(e)
        threading.Thread(target=work,daemon=True).start()
    def show_login(self):
        self.clear("Family Safety • Parent"); self.content.add_widget(self.label("Safe, consent-based parent controller\nThe child must visibly accept pairing and can turn sharing off.",14,MUTED,70)); server=self.input("Render server URL",value=self.client.base); email=self.input("Parent email"); password=self.input("Password (12+ characters)",True); self.content.add_widget(self.label("SERVER",11,MUTED,24)); self.content.add_widget(server); self.content.add_widget(self.label("PARENT ACCOUNT",11,MUTED,24)); self.content.add_widget(email); self.content.add_widget(password)
        self.content.add_widget(self.button("Login",lambda:self.api(lambda:self._set_server(server) or self.client.login(email.text.strip(),password.text,"parent"),lambda _:self.dashboard()),BLUE)); self.content.add_widget(self.button("Create parent account",lambda:self.api(lambda:self._set_server(server) or self.client.register(email.text.strip(),password.text,"parent"),lambda r:self.message(r.get("message","Account created; now login"))))); self.content.add_widget(self.button("Check Render backend",lambda:self.api(lambda:self._set_server(server) or self.client._send("GET","/health"),lambda r:self.message("Backend online: "+str(r))),PANEL))
    def _set_server(self, field): self.client.set_url(field.text); return None
    def dashboard(self):
        self.clear("Parent Controller"); self.content.add_widget(self.label("LIVE • Render backend\nOnly linked child devices are visible.",14,MUTED,60)); self.content.add_widget(self.button("Refresh child devices",self.load_children,BLUE)); self.content.add_widget(self.button("Create one-time pairing code",self.pair)); self.content.add_widget(self.button("Logout",self.logout,PANEL)); self.children_box=BoxLayout(orientation="vertical",spacing=dp(8),size_hint_y=None); self.children_box.bind(minimum_height=self.children_box.setter("height")); self.content.add_widget(self.children_box); self.load_children()
    def load_children(self):
        if not hasattr(self,"children_box"): return
        self.children_box.clear_widgets(); self.children_box.add_widget(self.label("Checking for devices...",14,MUTED,48)); self.api(lambda:self.client.request("GET","/children"),self.show_children)
    def show_children(self,data):
        self.children_box.clear_widgets(); rows=data.get("children",[]) if isinstance(data,dict) else data
        if not rows: self.children_box.add_widget(self.label("No paired children yet. Generate a code and share it in person.",14,MUTED,70)); return
        for child in rows:
            cid=child.get("id") or child.get("child_id"); name=child.get("email",child.get("name","Child")); self.children_box.add_widget(self.button(f"{name}\nDevice: {child.get('device_id','—')}",lambda c=cid:self.controller(c),PANEL))
    def pair(self): self.api(lambda:self.client.request("POST","/devices/pairing-codes"),lambda r:self.message("Pairing code: "+str(r.get("code","created"))))
    def controller(self,child_id):
        self.clear("Device Controller"); self.content.add_widget(self.label("Child device controls are visible and consent-based.",14,MUTED,55)); self.content.add_widget(self.button("Latest location",lambda:self.api(lambda:self.client.request("GET",f"/location/latest/{child_id}"),lambda r:self.message(str(r))))); self.content.add_widget(self.button("Location history",lambda:self.api(lambda:self.client.request("GET",f"/location/history/{child_id}"),lambda r:self.message(str(r))))); self.content.add_widget(self.button("Request check-in",lambda:self.api(lambda:self.client.request("POST","/checkins/request",{"child_id":child_id,"reminder_minutes":15}),lambda r:self.message("Check-in requested")),BLUE)); self.content.add_widget(self.button("SOS alerts",lambda:self.api(lambda:self.client.request("GET",f"/sos/{child_id}"),lambda r:self.message(str(r))))); self.content.add_widget(self.button("Device status",lambda:self.api(lambda:self.client.request("GET",f"/device/status/{child_id}"),lambda r:self.message(str(r))))); message=self.input("Message child"); self.content.add_widget(message); self.content.add_widget(self.button("Send visible message",lambda:self.api(lambda:self.client.request("POST","/messages",{"child_id":child_id,"body":message.text}),lambda r:self.message("Message sent")),BLUE)); self.content.add_widget(self.button("Back to devices",self.dashboard,PANEL))
    def logout(self): self.client.logout(); self.show_login()
    def on_stop(self): self.client.logout()

if __name__ == "__main__": ParentApp().run()
