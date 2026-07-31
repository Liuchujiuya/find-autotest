import logging  # Python 标准日志库，用于同时输出控制台和文件日志。
from pathlib import Path  # 路径工具，用于创建 testresult/logs 日志目录。


def get_logger(name: str = "findai-autotest") -> logging.Logger:
    """创建或复用项目统一 logger。"""
    log_dir = Path("testresult/logs")  # 日志文件统一放在测试结果目录下，便于归档。
    log_dir.mkdir(parents=True, exist_ok=True)  # 递归创建日志目录，目录已存在时不报错。

    logger = logging.getLogger(name)  # 按名称获取 logger，保证不同模块可以复用同一个实例。
    if logger.handlers:
        return logger  # 已配置过 handler 时直接返回，避免重复打印同一条日志。

    logger.setLevel(logging.INFO)  # 默认记录 INFO 及以上级别，兼顾信息量和噪音控制。
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")  # 统一日志格式，包含时间、级别、模块和消息。

    file_handler = logging.FileHandler(log_dir / "run.log", encoding="utf-8")  # 文件日志用于测试后排查问题。
    file_handler.setFormatter(formatter)  # 给文件日志设置同样的格式。
    logger.addHandler(file_handler)  # 将文件输出挂到 logger 上。

    stream_handler = logging.StreamHandler()  # 控制台日志用于运行时即时观察进度。
    stream_handler.setFormatter(formatter)  # 给控制台日志设置同样的格式。
    logger.addHandler(stream_handler)  # 将控制台输出挂到 logger 上。

    return logger  # 返回配置完成的 logger 给调用方使用。
