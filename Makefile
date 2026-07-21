# epsonctl — Built by John Varghese (J0X) | https://github.com/John-Varghese-EH

PYTHON ?= python3
VERSION := $(shell $(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
APP_ID := dev.epsonctl.EpsonCtl

.PHONY: run test lint appimage flatpak deb aur dist-tar clean

run:
	@echo "Starting epsonctl $(VERSION) …"
	glib-compile-resources --sourcedir=data data/epsonctl.gresource.xml --target=data/epsonctl.gresource
	$(PYTHON) -m venv .venv --system-site-packages 2>/dev/null || true
	.venv/bin/pip install -q -e . 2>/dev/null || true
	.venv/bin/epsonctl

test:
	$(PYTHON) -m venv .venv --system-site-packages 2>/dev/null || true
	.venv/bin/pip install -q -e ".[dev]" 2>/dev/null || true
	.venv/bin/python -m pytest tests/ -v

lint:
	$(PYTHON) -m venv .venv --system-site-packages 2>/dev/null || true
	.venv/bin/pip install -q ruff 2>/dev/null || true
	.venv/bin/ruff check src/ tests/

appimage:
	@echo "Building AppImage for epsonctl $(VERSION) …"
	bash packaging/build-appimage.sh

flatpak:
	flatpak-builder --user --install --force-clean build-dir packaging/flatpak/$(APP_ID).yml

deb:
	@echo "Building Debian package for epsonctl $(VERSION) …"
	glib-compile-resources --sourcedir=data data/epsonctl.gresource.xml --target=data/epsonctl.gresource
	mkdir -p build-deb
	cp -r src data tests docs packaging Makefile pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md run.sh build-deb/
	cp -r packaging/debian build-deb/
	cd build-deb && dpkg-buildpackage -us -uc -b
	mkdir -p dist
	mv *.deb dist/
	rm -rf build-deb

aur: dist-tar
	@echo "Preparing AUR package for epsonctl $(VERSION) …"
	glib-compile-resources --sourcedir=data data/epsonctl.gresource.xml --target=data/epsonctl.gresource
	mkdir -p build-aur
	cp PKGBUILD build-aur/
	cp dist/epsonctl-$(VERSION).tar.gz build-aur/
	cd build-aur && makepkg -s --sign
	mkdir -p dist
	mv build-aur/*.pkg.tar.zst dist/ || true
	rm -rf build-aur

dist-tar:
	@echo "Building tarball epsonctl-$(VERSION).tar.gz …"
	mkdir -p dist
	tar czf dist/epsonctl-$(VERSION).tar.gz \
		--transform='s,^,epsonctl-$(VERSION)/,' \
		--exclude='.git' --exclude='__pycache__' --exclude='.venv' \
		--exclude='dist' --exclude='build-dir' --exclude='reference' \
		--exclude='*.egg-info' \
		src/ data/ tests/ docs/ packaging/ PKGBUILD \
		pyproject.toml Makefile LICENSE README.md \
		THIRD_PARTY_NOTICES.md run.sh
	@echo "Created dist/epsonctl-$(VERSION).tar.gz"

clean:
	rm -rf .venv dist build-dir *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
