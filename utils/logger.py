import logging
import os
from datetime import datetime

def setup_logger(name, path='./logs/'):
    BASE_LOGPATH = path
    if not os.path.exists(BASE_LOGPATH):
        os.makedirs(BASE_LOGPATH)

    # Map string values to their equivalent logging levels
    level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING,
                 'ERROR': logging.ERROR, 'CRITICAL': logging.CRITICAL}
    
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')  # Default to 'DEBUG' if no env var set

    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%d-%m-%Y:%H:%M:%S',
        level=level_map.get(LOG_LEVEL, logging.DEBUG),
        filename=os.path.join(BASE_LOGPATH, f"{name}.log")
    )
    return logging.getLogger(name)
