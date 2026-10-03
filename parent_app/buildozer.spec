[app]
title = Family Safety Parent
package.name = safetyparent
package.domain = org.consentsafety
source.dir = .
source.include_exts = py,png,jpg,kv,json
version = 1.0.0
requirements = python3,kivy==2.2.1,kivymd==2.0.0,pillow,qrcode,websocket-client,certifi,pyjnius
orientation = portrait
fullscreen = 0
android.api = 35
android.minapi = 24
android.archs = arm64-v8a
android.permissions = INTERNET,ACCESS_NETWORK_STATE
# Set this to False and require HTTPS before releasing outside a private development LAN.
android.allow_cleartext_traffic = True
android.accept_sdk_license = True
p4a.branch = release-2024.01.21
[buildozer]
log_level = 2
warn_on_root = 1
