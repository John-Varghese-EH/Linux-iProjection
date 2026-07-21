# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH

# AppImage Build Notes

Building AppImages for GTK4 and libadwaita Python apps requires careful handling of system dependencies.

## Challenges
1. **GTK4/libadwaita:** Modern GNOME apps depend on libraries that are typically present on the host but can be version-incompatible.
2. **GSettings Schemas:** The app needs access to compiled schemas (`glib-compile-schemas`).
3. **Icons & Pixbuf:** Need to bundle `gdk-pixbuf-query-loaders` correctly.

## Workaround & Build Process
The script `build-appimage.sh` demonstrates a simplified approach. For a robust build in production:
- Use `linuxdeploy` alongside `linuxdeploy-plugin-gtk` (GTK plugin).
- Bundle Python using `python-appimage` or by setting up an environment inside the AppDir.
- Ensure GSettings schemas are compiled and exported via `XDG_DATA_DIRS` in `AppRun`.
