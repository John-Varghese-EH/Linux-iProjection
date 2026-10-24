pkgname=linux-iprojection
pkgver=1.4.1
_srcver=1.4.1
pkgrel=1
pkgdesc="Native Linux control & casting app for Epson projectors"
arch=('any')
url="https://github.com/John-Varghese-EH/Linux-iProjection"
license=('AGPL-3.0-or-later')
depends=('python' 'python-gobject' 'python-zeroconf' 'gtk4' 'libadwaita')
optdepends=(
  'python-pillow: system tray icon rendering'
  'python-pystray: system tray menu support'
  'gst-plugins-good: RTP streaming pipeline'
  'gst-plugins-bad: additional hardware video encoders and WebRTC'
  'gst-plugin-pipewire: Wayland screen capture portal integration'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=("$pkgname-$pkgver.tar.gz::$url/releases/download/v$pkgver/$pkgname-$_srcver.tar.gz")
sha256sums=('8059cd82137d451b0679218e1f28bb2307f0cbbfb4642af0ac1d0240c29e14f5')

build() {
  cd "$srcdir"
  if [ -d "$pkgname-$_srcver" ]; then
    cd "$pkgname-$_srcver"
  elif [ -d "linux_iprojection-$_srcver" ]; then
    cd "linux_iprojection-$_srcver"
  elif [ -d "Linux-iProjection-$_srcver" ]; then
    cd "Linux-iProjection-$_srcver"
  fi
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir"
  if [ -d "$pkgname-$_srcver" ]; then
    cd "$pkgname-$_srcver"
  elif [ -d "linux_iprojection-$_srcver" ]; then
    cd "linux_iprojection-$_srcver"
  elif [ -d "Linux-iProjection-$_srcver" ]; then
    cd "Linux-iProjection-$_srcver"
  fi
  python -m installer --destdir="$pkgdir" dist/*.whl

  # Install desktop file and icon
  install -Dm644 data/dev.linux_iprojection.LinuxIProjection.desktop "$pkgdir/usr/share/applications/dev.linux_iprojection.LinuxIProjection.desktop"
  install -Dm644 data/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg"
  install -Dm644 data/dev.linux_iprojection.LinuxIProjection.metainfo.xml "$pkgdir/usr/share/metainfo/dev.linux_iprojection.LinuxIProjection.metainfo.xml"
  install -Dm644 data/linux_iprojection.gresource "$pkgdir/usr/share/linux-iprojection/linux_iprojection.gresource"
}
