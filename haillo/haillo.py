from subprocess import call

import os
import logger
import config

logging = logger.Logger()
logging.setLevel(logger.INFO)


def main():
    session = os.path.join(config.root, 'haillo.vim')
    call(['vim', '-S', session, '-c', 'Haillo'])
