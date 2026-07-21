pkgname=epsonctl
pkgver=0.1.0
pkgrel=1
pkgdesc="Native Linux control & casting app for Epson projectors"
arch=('any')
url="https://github.com/John-Varghese-EH/EPSON-iProjection-For-Linux"
license=('AGPL3')
depends=('python' 'python-gobject' 'python-zeroconf' 'gtk4' 'libadwaita')
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
  cd "$srcdir/$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl

  # Install desktop file and icon
  install -Dm644 data/dev.epsonctl.EpsonCtl.desktop "$pkgdir/usr/share/applications/dev.epsonctl.EpsonCtl.desktop"
  install -Dm644 data/icons/hicolor/scalable/apps/dev.epsonctl.EpsonCtl.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/dev.epsonctl.EpsonCtl.svg"
  install -Dm644 data/dev.epsonctl.EpsonCtl.metainfo.xml "$pkgdir/usr/share/metainfo/dev.epsonctl.EpsonCtl.metainfo.xml"
  install -Dm644 data/epsonctl.gresource "$pkgdir/usr/share/epsonctl/epsonctl.gresource"
}
