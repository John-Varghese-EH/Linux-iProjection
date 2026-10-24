# Linux-iProjection Multi-Distribution Release & Store Guide

This guide covers building, packaging, and publishing `linux-iprojection` across all major Linux package managers and app stores.

---

## 1. Arch User Repository (AUR)

### Automated via GitHub Actions
Whenever a release tag (e.g. `v1.4.1`) is pushed, GitHub Actions automatically:
1. Builds `linux-iprojection-1.4.1.tar.gz`.
2. Computes the exact SHA256 checksum.
3. Automatically commits and pushes to `ssh://aur@aur.archlinux.org/linux-iprojection.git` (if `AUR_SSH_PRIVATE_KEY` secret is configured).

> **Important**:
> - In your AUR account settings, add your **SSH Public Key**: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOu7KvA1eIowDEiueCkaWlJk/9UxlD58XQNELUpD0Dsu`.
> - In your GitHub Repository Settings (`Settings -> Secrets and variables -> Actions -> New repository secret`), save the corresponding **SSH Private Key** (from `cat ~/.ssh/id_ed25519`) as `AUR_SSH_PRIVATE_KEY`.

### Manual 1-Command Sync (Optional)
If you prefer to sync AUR manually from your machine:
```bash
./packaging/aur/update-aur.sh v1.4.1
```

---

## 2. Ubuntu / Debian Launchpad PPA

Launchpad PPAs build native `.deb` binaries for all supported Ubuntu architectures (amd64, arm64, armhf) from a signed source package.

### Build Launchpad Source Package
```bash
# 1. Build the source package
make deb-src

# 2. Upload to your Launchpad PPA (e.g. ppa:cyber-trinity/linux-iprojection)
dput ppa:cyber-trinity/linux-iprojection /tmp/linux-iprojection-ppa.*/linux-iprojection_1.4.1-1_source.changes
```

### End-User Installation via PPA
```bash
sudo add-apt-repository ppa:cyber-trinity/linux-iprojection
sudo apt update
sudo apt install linux-iprojection
```

---

## 3. Flatpak & Flathub

A universal sandboxed package for all Linux distributions (Fedora, openSUSE, Arch, Debian, Ubuntu, etc.).

### Build Flatpak Locally
```bash
make flatpak
```

### Publishing to Flathub
1. Fork `https://github.com/flathub/flathub` or submit a new app pull request to Flathub:
   - Manifest: `packaging/flatpak/dev.linux_iprojection.LinuxIProjection.yml`
   - App ID: `dev.linux_iprojection.LinuxIProjection`
2. Test Flathub compliance with `flatpak-builder-lint`:
   ```bash
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest packaging/flatpak/dev.linux_iprojection.LinuxIProjection.yml
   ```
3. Once approved on Flathub, updates are deployed automatically on every GitHub release.

---

## 4. Snapcraft (Canonical Snap Store)

Deploy to Ubuntu Software Center and the Snap Store.

### Build Snap Locally
```bash
make snap
# Or run:
snapcraft --use-lxd
```

### Publish to Snap Store
```bash
# 1. Log in to your Canonical Snap developer account
snapcraft login

# 2. Register the snap name (first time only)
snapcraft register linux-iprojection

# 3. Upload and release to the stable channel
snapcraft upload linux-iprojection_1.4.1_amd64.snap --release=stable
```

### End-User Installation via Snap
```bash
sudo snap install linux-iprojection
```

---

## 5. PyPI (Python Package Index)

Allows users on any Linux distribution to install via pip:

```bash
# 1. Build sdist and wheel
python -m build

# 2. Upload to PyPI via twine
twine upload dist/linux_iprojection-1.4.1*
```

### End-User Installation via Pip
```bash
pip install --upgrade linux-iprojection
```
