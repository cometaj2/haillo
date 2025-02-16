|pypi| |pyver| |hclicore| |huckle| |hai|

Haillo
======

Haillo is a web frontend for hai (hcli_hai), the HCLI command line AI chat application.

----

Haillo is able to work with the hai HCLI application (hcli_hai) to interact with locally stored ai conversation contexts.

Note that a valid Anthropic API key has to be setup for hcli_hai to be usable. see hai help after hooking to it with huckle (see installation instructions below).

Help shape HCLI and it's ecosystem by raising issues on github!

[1] http://hcli.io

Related HCLI Projects
---------------------

- hcli_core, an HCLI Connector that can be used to expose a REST API that behaves as a CLI [2]

- huckle is a CLI, and python library, that can act as an impostor for any CLI expressed via hypertext command line interface (HCLI) semantics [3]

- hcli_hai, a python package wrapper that contains an HCLI sample application (hai); hai is an HCLI for interacting with Anthropic's Claude models via terminal input and output streams. [4]

[2] https://github.com/cometaj2/hcli_core

[3] https://github.com/cometaj2/huckle

[4] https://github.com/cometaj2/hcli_hai


Installation
------------

haillo requires a supported version of Python and pip.

You'll need an WSGI compliant application server to run haillo. For example, you can use Green Unicorn (https://gunicorn.org/).

.. code-block:: console

    pip install haillo
    pip install huckle
    pip install hcli_hai
    pip install hcli_core
    pip install gunicorn
    gunicorn --workers=1 --threads=100 -b 0.0.0.0:10000 "hcli_core:connector(\"`hcli_hai path`\")"
    huckle cli install localhost:10000
    gunicorn --preload --workers=4 --threads=100 -b 127.0.0.1:8000 --chdir `haillo path` "haillo:webapp()"

Usage
-----

.. code-block:: console

    haillo help
    hcli_hai help
    huckle help
    hcli_core help
    hai help

Versioning
----------

This project makes use of semantic versioning (http://semver.org) and may make use of the "devx",
"prealphax", "alphax" "betax", and "rcx" extensions where x is a number (e.g. 0.3.0-prealpha1)
on github. Only full major.minor.patch releases will be pushed to pip from now on.

Supports
--------

- Interacting with an hcli_hai (hai HCLI application) backend via the huckle hcli client.

To Do
-----

- TBD

Bugs
----

- TBD

.. |pypi| image:: https://img.shields.io/pypi/v/haillo?label=haillo
   :target: https://pypi.org/project/haillo
.. |pyver| image:: https://img.shields.io/pypi/pyversions/haillo.svg
   :target: https://pypi.org/project/haillo
.. |hclicore| image:: https://img.shields.io/pypi/v/hcli-core?label=hcli-core
   :target: https://pypi.org/project/hcli-core
.. |huckle| image:: https://img.shields.io/pypi/v/huckle?label=huckle
   :target: https://pypi.org/project/huckle
.. |hai| image:: https://img.shields.io/pypi/v/hcli-hc?label=hcli-hai
   :target: https://pypi.org/project/hcli-hai
