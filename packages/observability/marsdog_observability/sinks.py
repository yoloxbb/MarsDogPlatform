"""UTF-8 file rotation; record normalization/size limits belong to the runtime."""
from logging.handlers import RotatingFileHandler


class BoundedFileHandler(RotatingFileHandler):
    def __init__(self, filename, max_bytes=20 * 1024 * 1024, backups=4):
        super().__init__(filename, maxBytes=max_bytes, backupCount=backups, encoding="utf-8", delay=True)

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        return self.stream.tell() + len((self.format(record) + self.terminator).encode("utf-8")) > self.maxBytes
