import os
import logging
from logging.handlers import TimedRotatingFileHandler

os.makedirs("logs", exist_ok=True)

class NonBlockingLogger:
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = TimedRotatingFileHandler(
                filename="logs/balina_bot.log",
                when="midnight",
                backupCount=7,
                encoding="utf-8"
            )
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            import sys
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

    def info(self, msg, *args, **kwargs):
        self.logger.info(self._format(msg), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(self._format(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(self._format(msg), *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(self._format(msg), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(self._format(msg), *args, **kwargs)

    def _format(self, msg):
        return msg

def get_logger(name: str):
    return NonBlockingLogger(name)


