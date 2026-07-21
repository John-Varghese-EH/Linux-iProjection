"""
epsonctl - Main Entry Point
"""

import sys


def main():
    # If there are arguments (other than standard GTK flags or help/version)
    # Let's route strictly: if there are arguments and they are one of our CLI commands, route to CLI.
    # Otherwise route to GUI.

    # Check if the first argument is a valid CLI command or --help
    cli_commands = {"discover", "status", "power", "source", "volume", "wake", "-h", "--help"}

    # Are we trying to run a CLI command?
    run_cli = False
    if len(sys.argv) > 1 and sys.argv[1] in cli_commands:
        run_cli = True

    if run_cli:
        from .cli import main as cli_main

        sys.exit(cli_main())
    else:
        from .app import main as app_main

        sys.exit(app_main())


if __name__ == "__main__":
    main()
