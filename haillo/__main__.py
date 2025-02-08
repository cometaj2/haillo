from subprocess import call

import sys

from . import package
from . import config
from . import hutils


def main():
    if len(sys.argv) == 2:

        if sys.argv[1] == "--version":
            show_dependencies()

        elif sys.argv[1] == "help":
            display_man_page(config.manpage_path)
            sys.exit(0)

        elif sys.argv[1] == "path":
            print(config.root)
            sys.exit(0)

        elif sys.argv[1] == "run":
            print('gunicorn --preload --workers=1 --threads=100 -b 127.0.0.1:8000 --chdir `haillo path` "haillo:webapp()"')
#             print('waitress-serve --listen=127.0.0.1:8000 --threads=100 haillo:app')
#             print('gunicorn --workers=1 --threads=100 --timeout=30 --keep-alive=5 --graceful-timeout=10 -b 127.0.0.1:8000 "haillo:webapp()"')
#             print('waitress-serve --max-request-header-size=262144 --clear-untrusted-proxy-headers --listen=127.0.0.1:8000 --channel-timeout=30 --asyncore-use-poll --cleanup-interval=5 haillo:app')
            sys.exit(0)

        else:
            help()

    else:
        help()

def show_dependencies():
    def parse_dependency(dep_string):
        # Common version specifiers
        specifiers = ['==', '>=', '<=', '~=', '>', '<', '!=']

        # Find the first matching specifier
        for specifier in specifiers:
            if specifier in dep_string:
                name, version = dep_string.split(specifier, 1)
                return name.strip(), specifier, version.strip()

        # If no specifier found, return just the name
        return dep_string.strip(), '', ''

    dependencies = ""
    for dep in package.dependencies:
        name, specifier, version = parse_dependency(dep)
        if version:  # Only add separator if there's a version
            dependencies += f" {name}/{version}"
        else:
            dependencies += f" {name}"

    print(f"haillo/{package.__version__}{dependencies}")

def help():
    hutils.eprint("for help, use:\n")
    hutils.eprint("  haillo help")
    sys.exit(2)

# displays a man page (file) located on a given path
def display_man_page(path):
    call(["man", path])
