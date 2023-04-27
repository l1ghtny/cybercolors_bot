import datetime
import logging
from datetime import date, timedelta


class MyTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(self, when='m', interval=5, filename='timed_log', encoding='utf-8'):
        super().__init__(
            filename=filename,
            when=when,
            interval=interval,
            encoding=encoding,
        )
        self.namer = rotator_namer


def rotator_namer(filename):
    now = datetime.datetime.now().strftime('%d-%m-%y_%H-%M-%S')
    return filename.split('.log')[0] + '_' + now + '.log'
