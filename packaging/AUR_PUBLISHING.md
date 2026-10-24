# AUR (Arch User Repository) Publishing Guide

This document details the exact process for packaging, testing, and publishing `linux-iprojection` on the Arch User Repository (AUR).

---

## 1. Prerequisites for AUR Maintainers

1. **AUR Account**: Register at [https://aur.archlinux.org](https://aur.archlinux.org).
2. **SSH Key**: Add your public SSH key (`~/.ssh/id_ed25519.pub` or `~/.ssh/id_rsa.pub`) to your AUR profile account settings.
3. **Arch Linux or Arch Container/Chroot**: Ensure base development tools are installed:
   ```bash
   sudo pacman -S base-devel git
   ```

---

## 2. Testing the Package Locally

Before uploading to AUR, verify that `makepkg` successfully compiles and packages the project locally:

```bash
# 1. Ensure dist tarball exists or test directly
makepkg -si

# 2. Verify installed files
pacman -Ql linux-iprojection

# 3. Clean up build artifacts
rm -rf pkg/ src/ *.tar.zst
```

---

## 3. Publishing / Updating on AUR

Every AUR package is its own Git repository hosted on `aur.archlinux.org`.

### Step 3.1: Clone the AUR Repository
If publishing for the first time:
```bash
git clone ssh://aur@aur.archlinux.org/linux-iprojection.git /tmp/aur-linux-iprojection
cd /tmp/aur-linux-iprojection
```

### Step 3.2: Copy the PKGBUILD & Generate .SRCINFO
Copy `PKGBUILD` from this repository into the cloned AUR folder:
```bash
cp /path/to/EPSON-iProjection-For-Linux/PKGBUILD /tmp/aur-linux-iprojection/
cd /tmp/aur-linux-iprojection

# Regenerate .SRCINFO (mandatory on AUR)
makepkg --printsrcinfo > .SRCINFO
```

### Step 3.3: Verify Checksums
Ensure the checksum in `PKGBUILD` matches the release archive:
```bash
# To calculate SHA256 of the release tarball:
sha256sum linux-iprojection-1.4.1.tar.gz

# Or automatically update checksums in PKGBUILD:
updpkgsums
makepkg --printsrcinfo > .SRCINFO
```

### Step 3.4: Commit and Push to AUR
```bash
git add PKGBUILD .SRCINFO
git commit -m "Update to v1.4.1"
git push origin master
```

---

## 4. GitHub Release Tagging

For the AUR download URL (`$url/releases/download/v$pkgver/$pkgname-$_srcver.tar.gz`) to resolve:

1. Commit all version bumps and create the git tag:
   ```bash
   git tag -a v1.4.1 -m "Release v1.4.1 - Enterprise Resilience & Compatibility"
   git push origin main --tags
   ```

2. Build the distribution tarball:
   ```bash
   python -m build --sdist
   ```

3. Create the GitHub release for `v1.4.1` and upload `dist/linux_iprojection-1.4.1.tar.gz` (or `dist/linux-iprojection-1.4.1.tar.gz`).

---

## 5. Installing from AUR (End Users)

Once pushed to AUR, Arch Linux / Manjaro / EndeavourOS users can install with any AUR helper:

```bash
# Using yay
yay -S linux-iprojection

# Using paru
paru -S linux-iprojection
```
