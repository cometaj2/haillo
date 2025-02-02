import sys
import os
import importlib
import inspect

root = os.path.dirname(inspect.getfile(lambda: None))
manpage_path = root + "/data/haillo.1"
webapp_root = root + "/templates/"
