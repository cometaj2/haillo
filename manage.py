import os
import sys
import inspect
import subprocess
import importlib.util

# Direct import of package.py to avoid triggering haillo __init__ during the build process
spec = importlib.util.spec_from_file_location(
    "package",
    os.path.join(os.path.dirname(__file__), "haillo", "package.py")
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)

version = package.__version__

def write_requirements():
    with open('requirements.txt', 'w') as f:
        for dep in package.dependencies:
            f.write(f"{dep}\n")

if sys.argv[-1] == 'write-requirements':
    branch = subprocess.check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip().decode("utf-8")
    if branch != "master":
        sys.exit("dry-run from a branch other than master is disallowed.")
    write_requirements()

if sys.argv[-1] == 'dry-run':
    branch = subprocess.check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip().decode("utf-8")
    if branch != "master":
        sys.exit("dry-run from a branch other than master is disallowed.")
    os.system("pip uninstall -y haillo")
    os.system("rm -rf requirements.txt")
    write_requirements()
    os.system("rm -rf haillo.egg-info")
    os.system("rm -rf build")
    os.system("rm -rf dist")
    os.system("python -m build --sdist --wheel")
    os.system("twine check dist/*")
    os.system("pip install -e .")
    sys.exit()

if sys.argv[-1] == 'publish':
    branch = subprocess.check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip()
    if branch.decode('ASCII') != "master":
        sys.exit("publishing from a branch other than master is disallowed.")
    os.system("pip uninstall -y haillo")
    os.system("rm -rf requirements.txt")
    write_requirements()
    os.system("rm -rf haillo.egg-info")
    os.system("rm -rf build")
    os.system("rm -rf dist")
    os.system("python -m build --sdist --wheel")
    os.system("twine upload dist/* -r pypi")
    os.system("pip install -e .")
    os.system("git tag -a %s -m 'version %s'" % ("haillo-" + version, "haillo-" + version))
    os.system("git push")
    os.system("git push --tags")
    sys.exit()

if sys.argv[-1] == 'tag':
    branch = subprocess.check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip()
    if branch != "master":
        sys.exit("tagging from a branch other than master is disallowed.")
    os.system("git tag -a %s -m 'version %s'" % ("haillo-" + version, "haillo-" + version))
    sys.exit()
