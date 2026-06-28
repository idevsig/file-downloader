import os
import toml
import argparse
from urllib.parse import urlparse

__version__ = "0.1.2"


def load_config(service_name="fetcher"):
    """加载配置，优先级：命令行参数 > 配置文件 > 环境变量 > 默认值"""
    # 默认配置（使用小写键名）
    default_config = {
        "url": "tcp://test.mosquitto.org:1883",
        "transport": "tcp",
        "username": None,
        "password": None,
        "qos": 0,
        "keepalive": 60,
        "client_id": "file_downloader_client",
        "topic_subscribe": "file/download/request",
        "topic_publish": "file/download/complete",
        "topic_delete": "file/download/delete",
        "download_save_dir": "downloads",
        "download_web_url": "",
        "aria2_rpc_enable": False,
        "aria2_rpc_host": "http://localhost",
        "aria2_rpc_port": 6800,
        "aria2_rpc_token": "",
        "aria2_download_dir": "aria_downloads",
        "delete_remote_file": False,
        "download_timeout": 3600,
    }

    # 环境变量名映射（环境变量使用大写）
    env_key_mapping = {
        "url": "MQTT_URL",
        "transport": "TRANSPORT",
        "username": "USERNAME",
        "password": "PASSWORD",
        "qos": "QOS",
        "keepalive": "KEEPALIVE",
        "client_id": "CLIENT_ID",
        "topic_subscribe": "TOPIC_SUBSCRIBE",
        "topic_publish": "TOPIC_PUBLISH",
        "topic_delete": "TOPIC_DELETE",
        "download_save_dir": "DOWNLOAD_SAVE_DIR",
        "download_web_url": "DOWNLOAD_WEB_URL",
        "aria2_rpc_enable": "ARIA2_RPC_ENABLE",
        "aria2_rpc_host": "ARIA2_RPC_HOST",
        "aria2_rpc_port": "ARIA2_RPC_PORT",
        "aria2_rpc_token": "ARIA2_RPC_TOKEN",
        "aria2_download_dir": "ARIA2_DOWNLOAD_DIR",
        "delete_remote_file": "DELETE_REMOTE_FILE",
        "download_timeout": "DOWNLOAD_TIMEOUT",
    }

    # 初始化配置
    config = default_config.copy()

    # puller 专用配置
    if service_name == "puller":
        config["topic_subscribe"] = "file/download/complete"

    # 1. 加载环境变量（最低优先级）
    # 环境变量使用大写命名
    for config_key, env_key in env_key_mapping.items():
        env_value = os.getenv(env_key)
        if env_value is not None:
            try:
                if config_key in (
                    "qos",
                    "keepalive",
                    "aria2_rpc_port",
                    "aria2_rpc_enable",
                    "delete_remote_file",
                    "download_timeout",
                ):
                    config[config_key] = int(env_value)  # 类型转换
                else:
                    config[config_key] = env_value
                print(f"Loaded {config_key} from environment: {env_value}")
            except ValueError as e:
                print(
                    f"Invalid environment variable {env_key}: {env_value}, error: {e}"
                )

    # 2. 加载配置文件（覆盖环境变量）
    config_file = "config.toml"
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                file_config = toml.load(f)

            # 处理 mqtt 配置段
            mqtt_section = file_config.get("mqtt", {})
            for config_key in default_config:
                if config_key in mqtt_section:
                    try:
                        if config_key in ("qos", "keepalive"):
                            config[config_key] = int(
                                mqtt_section[config_key]
                            )  # 类型转换
                        else:
                            config[config_key] = mqtt_section[config_key]
                        print(
                            f"Loaded {config_key} from config file: {mqtt_section[config_key]}"
                        )
                    except ValueError as e:
                        print(
                            f"Invalid value for {config_key} in {config_file}: {mqtt_section[config_key]}, error: {e}"
                        )

            # 处理 aria2 配置段
            aria2_section = file_config.get("aria2", {})
            # aria2 配置段中的键名映射
            aria2_key_mapping = {
                "rpc_enable": "aria2_rpc_enable",
                "rpc_host": "aria2_rpc_host",
                "rpc_port": "aria2_rpc_port",
                "rpc_token": "aria2_rpc_token",
                "download_dir": "aria2_download_dir",
            }
            for file_key, config_key in aria2_key_mapping.items():
                if file_key in aria2_section and config_key in default_config:
                    try:
                        if config_key in ("aria2_rpc_port", "aria2_rpc_enable"):
                            config[config_key] = int(
                                aria2_section[file_key]
                            )  # 类型转换
                        else:
                            config[config_key] = aria2_section[file_key]
                        print(
                            f"Loaded {config_key} from config file: {aria2_section[file_key]}"
                        )
                    except ValueError as e:
                        print(
                            f"Invalid value for {file_key} in {config_file}: {aria2_section[file_key]}, error: {e}"
                        )

            # 处理 download 配置段
            download_section = file_config.get("download", {})
            download_key_mapping = {
                "save_dir": "download_save_dir",
                "web_url": "download_web_url",
            }
            for file_key, config_key in download_key_mapping.items():
                if file_key in download_section and config_key in default_config:
                    try:
                        config[config_key] = download_section[file_key]
                        print(
                            f"Loaded {config_key} from config file: {download_section[file_key]}"
                        )
                    except ValueError as e:
                        print(
                            f"Invalid value for {file_key} in {config_file}: {download_section[file_key]}, error: {e}"
                        )

            # 处理 puller 配置段
            puller_section = file_config.get("puller", {})
            puller_key_mapping = {
                "delete_remote_file": "delete_remote_file",
                "download_timeout": "download_timeout",
            }
            for file_key, config_key in puller_key_mapping.items():
                if file_key in puller_section and config_key in default_config:
                    try:
                        config[config_key] = int(puller_section[file_key])
                        print(
                            f"Loaded {config_key} from config file: {puller_section[file_key]}"
                        )
                    except ValueError as e:
                        print(
                            f"Invalid value for {file_key} in {config_file}: {puller_section[file_key]}, error: {e}"
                        )

        except Exception as e:
            print(f"Failed to load config file {config_file}: {e}")

    print()

    # 3. 解析命令行参数（最高优先级）
    parser = argparse.ArgumentParser(description="Video Downloader MQTT Client")
    parser.add_argument("--url", help="MQTT Broker URL (e.g., tcp://host:port, wss://host:port/path)")
    parser.add_argument("--qos", type=int, help="QoS level (0, 1, or 2)")
    parser.add_argument("--keepalive", type=int, help="MQTT Keepalive interval")
    parser.add_argument("--topic-subscribe", help="MQTT subscribe topic")
    parser.add_argument("--client-id", help="MQTT client ID")
    parser.add_argument("--username", help="MQTT username for authentication")
    parser.add_argument("--password", help="MQTT password for authentication")
    parser.add_argument(
        "--aria2-rpc-enable", type=int, help="Enable aria2 RPC (0 or 1)"
    )
    parser.add_argument("--download-web-url", help="Download web URL")

    parser.add_argument("--aria2-rpc-host", help="aria2 RPC host")
    parser.add_argument("--aria2-rpc-port", type=int, help="aria2 RPC port")
    parser.add_argument("--aria2-rpc-token", help="aria2 RPC token")
    parser.add_argument("--aria2-download-dir", help="aria2 RPC download directory")
    parser.add_argument(
        "--version",
        help="Show version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # fetcher 专用参数
    if service_name == "fetcher":
        parser.add_argument("--topic-publish", help="MQTT publish topic")
        parser.add_argument("--topic-delete", help="MQTT delete topic")
        parser.add_argument("--download-save-dir", help="Download save directory")

    # puller 专用参数
    if service_name == "puller":
        parser.add_argument(
            "--delete-remote-file",
            type=int,
            choices=[0, 1],
            help="Delete remote file after download (0 or 1)",
        )
        parser.add_argument(
            "--download-timeout",
            type=int,
            help="Download timeout in seconds (default: 3600)",
        )

    args = parser.parse_args()

    # 更新配置
    # 命令行参数到配置键的映射
    arg_key_mapping = {
        "url": "url",
        "qos": "qos",
        "keepalive": "keepalive",
        "topic_subscribe": "topic_subscribe",
        "client_id": "client_id",
        "username": "username",
        "password": "password",
        "aria2_rpc_enable": "aria2_rpc_enable",
        "aria2_rpc_host": "aria2_rpc_host",
        "aria2_rpc_port": "aria2_rpc_port",
        "aria2_rpc_token": "aria2_rpc_token",
        "aria2_download_dir": "aria2_download_dir",
        "topic_publish": "topic_publish",
        "topic_delete": "topic_delete",
        "download_save_dir": "download_save_dir",
        "download_web_url": "download_web_url",
        "delete_remote_file": "delete_remote_file",
        "download_timeout": "download_timeout",
    }

    for arg_key, config_key in arg_key_mapping.items():
        if config_key in default_config:
            arg_value = getattr(args, arg_key, None)
            if arg_value is not None:
                try:
                    config[config_key] = arg_value
                    print(f"Loaded {config_key} from command line: {arg_value}")
                except ValueError as e:
                    print(
                        f"Invalid command-line argument {arg_key}: {arg_value}, error: {e}"
                    )

    # 转换 aria2_rpc_enable 为布尔值
    config["aria2_rpc_enable"] = bool(config["aria2_rpc_enable"])

    # 转换 delete_remote_file 为布尔值
    config["delete_remote_file"] = bool(config["delete_remote_file"])

    # 解析 URL 并提取 host 和 port
    try:
        parsed = urlparse(config["url"])
        config["host"] = parsed.hostname or "test.mosquitto.org"
        config["port"] = parsed.port or 1883
        config["ws_path"] = parsed.path or "/mqtt"

        # 如果 URL 以 wss:// 开头，自动设置 transport 为 websockets
        if config["url"].startswith("wss://") or config["url"].startswith("ws://"):
            config["transport"] = "websockets"
            # 如果是 wss://，启用 TLS
            config["use_tls"] = config["url"].startswith("wss://")
        else:
            config["use_tls"] = False
    except Exception as e:
        print(f"Invalid URL: {config['url']}, error: {e}")
        config["host"] = "test.mosquitto.org"
        config["port"] = 1883
        config["ws_path"] = "/mqtt"
        config["use_tls"] = False

    # 验证配置
    if config["qos"] not in (0, 1, 2):
        print(f"Invalid qos: {config['qos']}, defaulting to 0")
        config["qos"] = 0
    if config["transport"] not in ("tcp", "websockets"):
        print(f"Invalid transport: {config['transport']}, defaulting to tcp")
        config["transport"] = "tcp"
    if config["port"] <= 0 or config["port"] > 65535:
        print(f"Invalid port: {config['port']}, defaulting to 1883")
        config["port"] = 1883
    if config["aria2_rpc_port"] <= 0 or config["aria2_rpc_port"] > 65535:
        print(f"Invalid aria2_rpc_port: {config['aria2_rpc_port']}, defaulting to 6800")
        config["aria2_rpc_port"] = 6800
    if not config["download_save_dir"]:
        print("Invalid download_save_dir, defaulting to 'downloads'")
        config["download_save_dir"] = "downloads"
    if config["download_web_url"] and not config["download_web_url"].endswith("/"):
        config["download_web_url"] += "/"

    print()
    return config
