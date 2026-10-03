"""Foreground service, started only by the child's explicit location-sharing action.

Buildozer declares foregroundServiceType=location. Android shows its persistent service
notification; no stealth/background workaround and no background-location permission.
"""
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jnius import PythonJavaClass, autoclass, java_method

argument = json.loads(os.environ["PYTHON_SERVICE_ARGUMENT"])
server_url = argument["url"].rstrip("/")
access = argument["access"]
refresh = argument["refresh"]
child_id = argument["child_id"]
interval = max(60, min(900, int(argument.get("interval", 90))))
queue = deque(maxlen=50)


def send(method, path, payload, retry=True):
    global access, refresh
    body = json.dumps(payload).encode()
    request = Request(server_url + path, data=body, headers={"Authorization": "Bearer " + access,
                                                             "Content-Type": "application/json"}, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read())
    except HTTPError as error:
        if error.code != 401 or not retry:
            raise
        renewed = Request(server_url + "/auth/location-session/refresh", data=json.dumps({"refresh_token": refresh}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(renewed, timeout=12) as response:
            tokens = json.loads(response.read())
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        return send(method, path, payload, retry=False)


class Listener(PythonJavaClass):
    __javainterfaces__ = ["android/location/LocationListener"]
    __javacontext__ = "app"

    @java_method("(Landroid/location/Location;)V")
    def onLocationChanged(self, point):
        age_seconds = (time.time() * 1000 - point.getTime()) / 1000
        if age_seconds < 0 or age_seconds > 300:
            return
        queue.append({"latitude": point.getLatitude(), "longitude": point.getLongitude(),
                      "accuracy": max(0.0, point.getAccuracy()),
                      "recorded_at": datetime.fromtimestamp(point.getTime() / 1000, timezone.utc).isoformat(),
                      "battery": battery()[0], "network": network()})

    @java_method("(Ljava/lang/String;)V")
    def onProviderEnabled(self, provider):
        return None

    @java_method("(Ljava/lang/String;)V")
    def onProviderDisabled(self, provider):
        return None

    @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
    def onStatusChanged(self, provider, status, extras):
        return None


def battery():
    intent = service.registerReceiver(None, autoclass("android.content.IntentFilter")("android.intent.action.BATTERY_CHANGED"))
    if intent is None:
        return None, None
    level, scale, state = intent.getIntExtra("level", -1), intent.getIntExtra("scale", -1), intent.getIntExtra("status", -1)
    value = int(level * 100 / scale) if level >= 0 and scale > 0 else None
    return value, state in (2, 5)


def network():
    try:
        manager = service.getSystemService(autoclass("android.content.Context").CONNECTIVITY_SERVICE)
        info = manager.getActiveNetworkInfo()
        if info is None or not info.isConnected():
            return "offline"
        return "wifi" if info.getType() == 1 else "cellular"
    except Exception:
        return "unknown"


service = autoclass("org.kivy.android.PythonService").mService
context = autoclass("android.content.Context")
locations = service.getSystemService(context.LOCATION_SERVICE)
listener = Listener()
providers = []
try:
    looper = autoclass("android.os.Looper").getMainLooper()
    for provider in ("gps", "network"):
        if locations.isProviderEnabled(provider):
            locations.requestLocationUpdates(provider, interval * 1000, 30.0, listener, looper)
            providers.append(provider)
    # No sticky restart: the service must not resume without a child's active consent.
    failures = 0
    while True:
        if not providers:
            for provider in ("gps", "network"):
                if locations.isProviderEnabled(provider):
                    locations.requestLocationUpdates(provider, interval * 1000, 30.0, listener, looper)
                    providers.append(provider)
        try:
            charge, charging = battery()
            send("POST", "/device/status", {"online": True, "battery": charge, "charging": charging,
                                               "network": network(), "location_enabled": bool(providers),
                                               "notifications_enabled": True, "sharing": True})
            while queue:
                send("POST", "/location", queue[0])
                queue.popleft()
            failures = 0
        except HTTPError as error:
            if error.code in (401, 403, 404):
                service.stopSelf()  # revoked or expired credentials end the foreground service
                break
            failures = min(failures + 1, 6)
        except (URLError, TimeoutError, OSError, ValueError):
            failures = min(failures + 1, 6)
        time.sleep(min(300, max(interval, 2 ** failures * 5)))
finally:
    locations.removeUpdates(listener)
