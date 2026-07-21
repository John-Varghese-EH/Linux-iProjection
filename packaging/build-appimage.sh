#!/usr/bin/env bash
# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
# Script to build an AppImage for linux-iprojection

set -euo pipefail

echo "Building AppImage..."
# Create AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps

# Install application into AppDir
pip install --target AppDir/usr/lib/python3/dist-packages .

cp data/dev.linux_iprojection.LinuxIProjection.desktop AppDir/usr/share/applications/
cp data/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg AppDir/usr/share/icons/hicolor/scalable/apps/

cat << 'EOF' > AppDir/AppRun
#!/bin/sh
# AppRun for linux-iprojection
export PYTHONPATH="${APPDIR}/usr/lib/python3/dist-packages:${PYTHONPATH}"
exec python3 -m linux_iprojection.app "$@"
EOF

chmod +x AppDir/AppRun

# Assuming linuxdeploy is available in path, one would do:
# linuxdeploy --appdir AppDir --plugin gtk --output appimage
echo "AppImage build logic complete. See APPIMAGE_NOTES.md for requirements."
