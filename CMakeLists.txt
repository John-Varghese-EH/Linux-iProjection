cmake_minimum_required(VERSION 3.16)
project(linux-iprojection VERSION 1.3.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Options
option(BUILD_TESTS "Build test suite" ON)

# Find GStreamer dependencies
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)
pkg_check_modules(GST_WEBRTC gstreamer-webrtc-1.0)  # Optional: for WebRTC streaming
pkg_check_modules(GLIB REQUIRED glib-2.0 gobject-2.0)

include_directories(
    ${GST_INCLUDE_DIRS}
    ${GLIB_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

# Custom target for Python installation / virtual environment setup
add_custom_target(python_install
    COMMAND ${CMAKE_COMMAND} -E echo "Installing Python package..."
    COMMAND python3 -m pip install -e .
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)

# Installation targets for desktop environment integration
install(DIRECTORY data/icons/ DESTINATION share/icons)
install(FILES data/dev.linux_iprojection.LinuxIProjection.desktop DESTINATION share/applications)
install(FILES data/dev.linux_iprojection.LinuxIProjection.metainfo.xml DESTINATION share/metainfo)

# Packaging via CPack
set(CPACK_PACKAGE_NAME "linux-iprojection")
set(CPACK_PACKAGE_VENDOR "John Varghese (J0X)")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Native Linux Epson iProjection streaming driver and client")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_GENERATOR "DEB;RPM;TGZ")
set(CPACK_DEBIAN_PACKAGE_MAINTAINER "John Varghese <cyber-trinity@users.noreply.github.com>")
set(CPACK_DEBIAN_PACKAGE_DEPENDS "python3 (>= 3.10), python3-gi, python3-zeroconf, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, pipewire")

include(CPack)
