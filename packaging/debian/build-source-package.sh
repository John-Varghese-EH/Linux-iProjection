#!/usr/bin/env bash
# Build an Ubuntu Launchpad PPA Source Package for linux-iprojection
set -euo pipefail

PPA="${1:-ppa:cyber-trinity/linux-iprojection}"
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

echo "==> Building Launchpad Source Package for linux-iprojection v${VERSION}..."

# 1. Compile GResource
glib-compile-resources --sourcedir=data data/linux_iprojection.gresource.xml --target=data/linux_iprojection.gresource

# 2. Prepare clean source directory
WORK_DIR=$(mktemp -d /tmp/linux-iprojection-ppa.XXXXXX)
PKG_DIR="${WORK_DIR}/linux-iprojection-${VERSION}"
mkdir -p "$PKG_DIR"

# 3. Create orig.tar.gz
make dist-tar
cp "dist/linux-iprojection-${VERSION}.tar.gz" "${WORK_DIR}/linux-iprojection_${VERSION}.orig.tar.gz"

# 4. Extract into package directory
tar -xzf "${WORK_DIR}/linux-iprojection_${VERSION}.orig.tar.gz" -C "$WORK_DIR"
cp -r packaging/debian "$PKG_DIR/"

# 5. Build source package
cd "$PKG_DIR"
if [ -n "${GPG_KEY_ID:-}" ]; then
    dpkg-buildpackage -S -sa -d -k"${GPG_KEY_ID}"
else
    dpkg-buildpackage -S -sa -d -us -uc
    echo ""
    echo "Notice: Package was built unsigned (-us -uc)."
    echo "To sign for Launchpad, run:"
    echo "  debsign -k <YOUR-GPG-KEY-ID> ${WORK_DIR}/linux-iprojection_${VERSION}-1_source.changes"
fi

echo ""
echo "==> Source package files generated in ${WORK_DIR}:"
ls -la "${WORK_DIR}"/*.dsc "${WORK_DIR}"/*_source.changes "${WORK_DIR}"/*.debian.tar.* 2>/dev/null || true

echo ""
echo "==> To upload to Launchpad PPA:"
echo "  dput ${PPA} ${WORK_DIR}/linux-iprojection_${VERSION}-1_source.changes"
