[app]
title = Family Safety Child
package.name = safekid
package.domain = org.consentsafety
source.dir = .
source.include_exts = py,png,jpg,kv,json
version = 1.0.0
requirements = python3,kivy==2.2.1,kivymd==2.0.0,pillow,qrcode,websocket-client,certifi,pyjnius,plyer
orientation = portrait
fullscreen = 0
android.api = 35
android.minapi = 24
android.archs = arm64-v8a
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_COARSE_LOCATION,ACCESS_FINE_LOCATION,POST_NOTIFICATIONS,CAMERA,RECORD_AUDIO,FOREGROUND_SERVICE,FOREGROUND_SERVICE_LOCATION
services = location:service/location_service.py:foreground:foregroundServiceType=location
# Local LAN development only; disable before release and use HTTPS.
android.allow_cleartext_traffic = True
android.accept_sdk_license = True
p4a.branch = release-2024.01.21
[buildozer]
log_level = 2
warn_on_root = 1
