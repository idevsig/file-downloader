import os
import logging

def setup_logging(name: str):
    """配置日志记录"""

    # 确保下载目录存在
    log_path = "logs"
    if not os.path.exists(log_path):
        os.makedirs(log_path)   

    output_path = os.path.join(log_path, f'file_{name}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        # format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(output_path),
            logging.StreamHandler()
        ]
    )
