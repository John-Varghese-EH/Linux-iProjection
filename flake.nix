{
  description = "linux-iprojection — native Linux control & casting app for Epson projectors";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Python environment with the GTK/GStreamer bindings and test tooling.
        python = pkgs.python312;
        pythonEnv = python.withPackages (ps: with ps; [
          pygobject3
          pycairo
          pytest
          pytest-asyncio
          pytest-mock
          ruff
          zeroconf
          pystray
          pillow
          distro
        ]);

        # GStreamer core + base for the Python bindings and unit tests. The
        # H.264 encoder is bundled inside the Flatpak (see packaging/flatpak),
        # so no GPL codecs need to be compiled here.
        gstInputs = with pkgs.gst_all_1; [
          gstreamer
          gst-plugins-base
          gst-plugins-good
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          name = "linux-iprojection-dev";

          nativeBuildInputs = [
            pkgs.gobject-introspection
            pkgs.pkg-config
          ];

          buildInputs = [
            pythonEnv
            pkgs.glib
            pkgs.gtk4
            pkgs.libadwaita
            pkgs.flatpak
            pkgs.flatpak-builder
            pkgs.desktop-file-utils
            pkgs.appstream
          ] ++ gstInputs;

          shellHook = ''
            echo "linux-iprojection development shell (nixos-unstable)"
            echo "  run unit tests : make test"
            echo "  run linter     : make lint"
            echo "  build flatpak  : make flatpak"
          '';
        };

        # A shell that also bundles gst-plugins-ugly (x264enc) so the GStreamer
        # encode test can be run directly against the host for diagnostics.
        devShells.full = pkgs.mkShell {
          name = "linux-iprojection-dev-full";

          inputsFrom = [ self.devShells.${system}.default ];

          buildInputs = with pkgs.gst_all_1; [
            gst-plugins-ugly
            gst-libav
            gst-plugins-bad
          ];

          shellHook = ''
            echo "linux-iprojection development shell (full GStreamer, incl. x264enc)"
            echo "  encode test: bash tests/gstreamer/encode_test.sh"
          '';
        };
      });
}
