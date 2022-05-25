import logging.config


def setup_logging():
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'fmt': {
                'format': '%(asctime)s [%(levelname)s] (%(name)s) %(message)s'
            }
        },
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'formatter': 'fmt',
                'stream': 'ext://sys.stdout'
            },
            'stderr': {
                'class': 'logging.StreamHandler',
                'formatter': 'fmt',
                'stream': 'ext://sys.stderr'
            }
        },
        'loggers': {
            'icy': {
                'handlers': ['stdout'],
                'level': 'DEBUG',
                'propagate': False
            }
        },
        'root': {
            'handlers': ['stderr'],
            'level': 'WARNING',
            'propagate': False
        }
    })

