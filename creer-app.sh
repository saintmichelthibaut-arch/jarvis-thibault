#!/bin/bash
# Crée (ou met à jour) l'app ~/Applications/Jarvis.app : une vraie app Mac avec son icône,
# qui ouvre Jarvis dans sa propre fenêtre et peut utiliser le micro.
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
APP="$HOME/Applications/Jarvis.app"
VERSION="3"

# Déjà à jour ? On ne touche à rien (sinon macOS redemanderait les autorisations).
if [[ -f "$APP/Contents/Resources/version-jarvis" && "$(cat "$APP/Contents/Resources/version-jarvis")" == "$VERSION" ]]; then
  exit 0
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>com.thibault.jarvis</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>Jarvis</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>3.0</string>
  <key>CFBundleVersion</key><string>3</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Jarvis vous écoute quand vous lui parlez.</string>
  <key>NSCalendarsUsageDescription</key><string>Jarvis lit votre agenda pour vous faire le point.</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Jarvis" <<'SH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
JH="${JARVIS_HOME:-$HOME/.jarvis}"
bash "$JH/app/lancer.sh" --silencieux
exec "$JH/app/.venv/bin/python" -m jarvis_thibault.cli app
SH
chmod +x "$APP/Contents/MacOS/Jarvis"
echo "$VERSION" > "$APP/Contents/Resources/version-jarvis"

# Icône (à partir de l'image fournie avec Jarvis)
if [[ -f "$ICI/assets/icone.png" ]] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  SET="$(mktemp -d)/Jarvis.iconset"; mkdir -p "$SET"
  for t in 16 32 128 256 512; do
    sips -z $t $t "$ICI/assets/icone.png" --out "$SET/icon_${t}x${t}.png" >/dev/null || true
    sips -z $((t*2)) $((t*2)) "$ICI/assets/icone.png" --out "$SET/icon_${t}x${t}@2x.png" >/dev/null || true
  done
  iconutil -c icns "$SET" -o "$APP/Contents/Resources/Jarvis.icns" || true
fi
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
touch "$APP"
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[[ -x "$LSREG" ]] && "$LSREG" -f "$APP" >/dev/null 2>&1 || true
echo "  ✓ App Jarvis créée : $APP"
