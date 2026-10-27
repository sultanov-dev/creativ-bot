import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import config  # noqa: F401  (.env ni yuklaydi, LOG_LEVEL/DATA_DIR shundan o'qiladi)

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging() -> None:
    """Konsol + aylanuvchi fayl (DATA_DIR/logs/bot.log, 5 MB x 4 = ko'pi bilan 20 MB). Daraja: LOG_LEVEL (standart INFO)."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter = logging.Formatter(FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    handlers: list[logging.Handler] = [console]

    log_dir = os.path.join(config.DATA_DIR, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "bot.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError:
        # fayl yozib bo'lmasa ham bot konsolga yozib ishlayveradi
        pass

    logging.basicConfig(level=level, handlers=handlers, force=True)
    # har bir update uchun aiogram o'zi ham "handled" qatorini yozadi: bizning tg.in qatorlarimiz bilan takror
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
