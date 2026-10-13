"""Application setup; services and routes are composed by main.py."""
import os
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "QUANT_API_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

def configure_cors(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

BACKEND_LOG_PATH = Path(os.getenv("QUANT_BACKEND_LOG", str(Path(__file__).parent / "backend.log")))
BACKEND_LOG_MAX_BYTES = 10 * 1024 * 1024
BACKEND_LOG_BACKUP_COUNT = 3


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 其他模块可能在导入期调用过 basicConfig；仅在缺失时补齐控制台输出，避免重复 handler。
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        root.addHandler(console)
    already_rotating = any(
        isinstance(h, RotatingFileHandler) and Path(getattr(h, "baseFilename", "")) == BACKEND_LOG_PATH
        for h in root.handlers
    )
    if not already_rotating:
        try:
            file_handler = RotatingFileHandler(
                BACKEND_LOG_PATH,
                maxBytes=BACKEND_LOG_MAX_BYTES,
                backupCount=BACKEND_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            root.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger("momoQuantAPI").warning(f"backend.log 轮转文件句柄初始化失败: {exc}")



