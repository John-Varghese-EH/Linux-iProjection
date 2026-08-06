pkgname=linux-iprojection
pkgver=1.2.1
_srcver=1.2.1
pkgrel=1
pkgdesc="Native Linux control & casting app for Epson projectors"
arch=('any')
url="https://github.com/John-Varghese-EH/Linux-iProjection"
license=('AGPL3')
depends=('python' 'python-gobject' 'python-zeroconf' 'gtk4' 'libadwaita')
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=("$pkgname-$pkgver.tar.gz::$url/releases/download/v$pkgver/$pkgname-$_srcver.tar.gz")
sha256sums=('dc8408ce6adbaae044cf090a3d860bb67f48f38229b17419e4965760cf9e27ba')

build() {
  cd "$srcdir/$pkgname-$_srcver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$pkgname-$_srcver"
  python -m installer --destdir="$pkgdir" dist/*.whl

  # Install desktop file and icon
  install -Dm644 data/dev.linux_iprojection.LinuxIProjection.desktop "$pkgdir/usr/share/applications/dev.linux_iprojection.LinuxIProjection.desktop"
  install -Dm644 data/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/dev.linux_iprojection.LinuxIProjection.svg"
  install -Dm644 data/dev.linux_iprojection.LinuxIProjection.metainfo.xml "$pkgdir/usr/share/metainfo/dev.linux_iprojection.LinuxIProjection.metainfo.xml"
  install -Dm644 data/linux_iprojection.gresource "$pkgdir/usr/share/linux-iprojection/linux_iprojection.gresource"
}
