#!/usr/bin/env bash
# Update AUR package repository using the release tarball built by GitHub Actions
set -euo pipefail

TAG="${1:-v1.4.1}"
VERSION="${TAG#v}"
REPO="John-Varghese-EH/Linux-iProjection"
URL="https://github.com/${REPO}/releases/download/${TAG}/linux-iprojection-${VERSION}.tar.gz"

echo "==> Fetching GitHub Actions release tarball: $URL"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

if ! curl -fSL "$URL" -o "$TEMP_DIR/linux-iprojection-${VERSION}.tar.gz"; then
    echo "Error: Release tarball not found at $URL"
    echo "Ensure GitHub Actions has completed the release for tag $TAG."
    exit 1
fi

SHA256=$(sha256sum "$TEMP_DIR/linux-iprojection-${VERSION}.tar.gz" | awk '{print $1}')
echo "==> Calculated SHA256 checksum: $SHA256"

# Update local PKGBUILD
sed -i "s/^pkgver=.*/pkgver=${VERSION}/" PKGBUILD
sed -i "s/^_srcver=.*/_srcver=${VERSION}/" PKGBUILD
sed -i "s/^sha256sums=.*/sha256sums=('${SHA256}')/" PKGBUILD

# Update .SRCINFO
if command -v makepkg >/dev/null 2>&1; then
    makepkg --printsrcinfo > .SRCINFO
else
    sed -i "s/pkgver = .*/pkgver = ${VERSION}/" .SRCINFO
    sed -i "s/source = linux-iprojection-.*::/source = linux-iprojection-${VERSION}.tar.gz::/" .SRCINFO
    sed -i "s/download\/v[^\/]*\//download\/v${VERSION}\//" .SRCINFO
    sed -i "s/linux-iprojection-.*\.tar\.gz/linux-iprojection-${VERSION}.tar.gz/" .SRCINFO
    sed -i "s/sha256sums = .*/sha256sums = ${SHA256}/" .SRCINFO
fi

echo "==> PKGBUILD and .SRCINFO updated with GitHub Actions release checksum."
echo ""
echo "Next step: Push to AUR:"
echo "  git clone ssh://aur@aur.archlinux.org/linux-iprojection.git /tmp/aur"
echo "  cp PKGBUILD .SRCINFO /tmp/aur/"
echo "  cd /tmp/aur"
echo "  git add PKGBUILD .SRCINFO"
echo "  git commit -m 'Update to ${TAG}'"
echo "  git push origin master"
