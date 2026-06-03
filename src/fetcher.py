import paho.mqtt.client as mqtt
import json
import subprocess
import os
import time
import logging
import queue
import threading
from aria2s import Aria2cServer
from logger import setup_logging
from config import load_config
from utils import (
    extract_url_from_text,
    get_file_suffix,
    is_valid_m3u8_url,
    is_valid_magnet_url,
    truncate_filename,
)

# 文件路径记录：存储下载的文件信息 {file_name: full_path}
file_path_record = {}
file_path_record_lock = threading.Lock()

"""
爬取网络上的文件到服务器，并推送到MQTT服务器。
"""


def on_connect(client, userdata, flags, rc, *args, **kwargs):
    """
    MQTT 连接回调，兼容 MQTT 3.1/3.1.1 和 5.0。
    """
    logging.info(f"Connected to MQTT broker with result code {rc}")
    if rc == 0:
        config = userdata["config"]
        client.subscribe(config["topic_subscribe"], qos=config["qos"])
        logging.info(
            f"Subscribed to topic: {config['topic_subscribe']} with QoS {config['qos']}"
        )
        # 订阅删除主题
        if config.get("topic_delete"):
            client.subscribe(config["topic_delete"], qos=config["qos"])
            logging.info(
                f"Subscribed to delete topic: {config['topic_delete']} with QoS {config['qos']}"
            )
    else:
        logging.error(f"Failed to connect to MQTT broker: {rc}")


def on_message(client, userdata, msg):
    """
    MQTT 消息回调：将消息添加到队列中以进行顺序处理。
    """
    logging.info(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
    try:
        # 判断是否是删除主题的消息
        config = userdata["config"]
        if msg.topic == config.get("topic_delete"):
            # 直接处理删除请求，不放入队列
            handle_delete_request(msg)
        else:
            # Add message to the queue
            userdata["message_queue"].put((msg, time.time()))
            logging.info(f"Message queued for processing: {msg.payload.decode()}")
    except Exception as e:
        logging.error(f"Error queuing message: {str(e)}")


def delete_file(file_path):
    """
    删除指定的文件
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Deleted file: {file_path}")
            return True
        else:
            logging.warning(f"File not found: {file_path}")
            return False
    except Exception as e:
        logging.error(f"Error deleting file {file_path}: {str(e)}")
        return False


def handle_delete_request(msg):
    """
    处理删除请求消息
    消息格式: {"file_path": "xxx.mp4"} 或 {"name": "xxx.mp4"}
    """
    try:
        payload = msg.payload.decode("utf-8")
        logging.info(f"Processing delete request: {payload}")

        data = json.loads(payload)
        file_name = data.get("file_path") or data.get("name")

        if not file_name:
            logging.warning("Delete request missing file_path or name")
            return

        # 从记录中查找文件完整路径
        with file_path_record_lock:
            full_path = file_path_record.get(file_name)

        if full_path:
            if delete_file(full_path):
                # 删除成功后移除记录
                with file_path_record_lock:
                    file_path_record.pop(file_name, None)
                logging.info(f"File deleted and record removed: {file_name}")
            else:
                logging.error(f"Failed to delete file: {full_path}")
        else:
            logging.warning(f"File not found in record: {file_name}")

    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in delete request: {str(e)}")
    except Exception as e:
        logging.error(f"Error handling delete request: {str(e)}")


def download_file(
    ftype, url, save_name, save_dir, aria2server, m3u8_tool="vsd", overwrite=False
):
    """
    下载文件，支持 m3u8、magnet、http
    """
    # M3U8 不支持 aria2c 方式下载，只能单进程下载，所以这里将 aria2server 参数置为 None
    if ftype == "m3u8":
        save_name = save_name if save_name.endswith(".mp4") else save_name + ".mp4"
        return download_file_m3u8(url, save_name, save_dir, m3u8_tool, overwrite)
    else:
        # 如果不是磁力链接，则判断 save_name 后缀是否与 url 的后缀相同，若不同，则以 url 的文件后缀为准
        if not is_valid_magnet_url(url):
            url_suffix = get_file_suffix(url)
            file_suffix = get_file_suffix(save_name)
            if url_suffix != file_suffix:
                save_name += url_suffix
        return download_file_aria2(url, save_name, save_dir, aria2server)


def download_file_aria2(url, save_name, save_dir, aria2server: Aria2cServer):
    """
    使用 aria2 RPC 下载文件
    依赖 aria2c --enable-rpc
    """
    logging.info(f"Downloading file using aria2 RPC: {url}")
    try:
        return aria2server.download(url, save_dir, save_name)
    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")


def download_file_m3u8(url, save_name, save_dir="", tool="vsd", overwrite=False):
    """
    使用指定的工具下载 m3u8 文件
    依赖: vsd, m3u8-downloader
    """
    try:
        save_file_path = os.path.join(save_dir, save_name)

        # 判断文件是否已存在，若存在
        if os.path.exists(save_file_path):
            logging.info(f"File already exists: {save_file_path}")
            # 如果 overwrite 为 True，则删除文件，以便重新下载
            if overwrite:
                os.remove(save_file_path)
                logging.info(f"File deleted: {save_file_path}")
            else:
                # 直接返回文件名，表示文件已存在
                return save_name

        if tool == "vsd":
            command = ["vsd", "save", url]  # 使用引号包裹URL，防止空格导致问题
            if save_dir:
                command.extend(["-d", save_dir])
            command.extend(["-o", save_file_path])
        else:
            # m3u8-downloader 会自动添加 .mp4 后缀
            command = [
                "m3u8-downloader",
                "-u",
                url,
                "-o",
                save_name.replace(".mp4", ""),
            ]
            if save_dir:
                command.extend(["-sp", save_dir])

        logging.info(f"Executing command: {' '.join(command)}")
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="ignore",
            text=True,
        )
        if result.returncode == 0:
            # 等待文件下载完成（检查文件是否存在且大小稳定）
            logging.info(f"Waiting for file to be ready: {save_file_path}")
            max_wait_time = 300  # 最多等待5分钟
            check_interval = 2   # 每2秒检查一次
            waited_time = 0
            last_size = -1
            stable_count = 0
            
            while waited_time < max_wait_time:
                if os.path.exists(save_file_path):
                    current_size = os.path.getsize(save_file_path)
                    logging.info(f"File size: {current_size} bytes (waited {waited_time}s)")
                    
                    # 检查文件大小是否稳定（不再变化）
                    if current_size == last_size and current_size > 0:
                        stable_count += 1
                        if stable_count >= 3:  # 连续3次大小不变，认为下载完成
                            logging.info(f"File downloaded and stable: {save_name}")
                            return save_name
                    else:
                        stable_count = 0
                    
                    last_size = current_size
                
                time.sleep(check_interval)
                waited_time += check_interval
            
            # 超时后检查文件是否存在
            if os.path.exists(save_file_path) and os.path.getsize(save_file_path) > 0:
                logging.info(f"File exists after timeout: {save_name}")
                return save_name
            else:
                logging.error(f"File not found or empty after timeout: {save_file_path}")
                return None
        else:
            # 优先使用 stderr，其次使用 stdout
            error_output = result.stderr if result.stderr else result.stdout
            logging.error(f"Failed to download file. Error: {error_output}")
            return None
    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        # 尝试从 result 中获取错误信息
        if 'result' in locals():
            lines = (result.stdout + result.stderr).splitlines()
            error_lines = [line for line in lines if "error:" in line.lower()]
            if error_lines:
                logging.error(f"Error details: {error_lines}")
        return None


def process_message(client, config, aria2server, msg, receive_time):
    """
    处理单个 MQTT 消息。
    """
    try:
        payload = msg.payload.decode("utf-8")
        logging.info(f"Processing message: {payload}")

        # 下载文件名称
        name = None
        # 文件存在时是否覆盖
        overwrite = False

        # Parse message content
        try:
            data = json.loads(payload)
            url = data.get("url")
            name = data.get("name")
            overwrite = bool(data.get("overwrite", 0))
        except json.JSONDecodeError:
            url = extract_url_from_text(payload)

        if not url:
            logging.warning("No valid URL found in the message")
            return

        file_type = None
        if is_valid_m3u8_url(url):
            file_type = "m3u8"
        elif is_valid_magnet_url(url):
            file_type = "magnet"
        elif extract_url_from_text(url):
            file_type = "http"
        else:
            logging.warning(f"Invalid protocol for URL: {url}")
            return

        logging.info(f"Extracted URL: {url}, Name: {name}")

        timestamp = int(time.time())
        # 如果没有名称，则使用时间戳作为名称
        filename = name if name else f"file_{timestamp}"
        # 文件太长，导致处理失败，需要截断
        filename = truncate_filename(filename)

        file_path = download_file(
            file_type,
            url,
            filename,
            config["download_save_dir"],
            aria2server,
            overwrite=overwrite,
        )
        if file_path:
            # 记录文件路径，用于后续删除
            full_path = os.path.join(config["download_save_dir"], file_path)
            with file_path_record_lock:
                file_path_record[file_path] = full_path
            logging.info(f"Recorded file path: {file_path} -> {full_path}")
            download_http_url = ""
            if not is_valid_magnet_url(url) and config.get("download_web_url"):
                download_http_url = f"{config['download_web_url']}{file_path}"

            # Publish success message
            complete_msg = {
                "status": "success",
                "url": url,
                "name": name if name else "",
                "file_path": file_path,
                "download_url": download_http_url,
                "timestamp": timestamp,
                "receive_time": receive_time,
            }
            # print(complete_msg)
            result = client.publish(
                config["topic_publish"],
                json.dumps(complete_msg, ensure_ascii=False),
                qos=config["qos"],
            )
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logging.info(f"Published completion message for {url}")
            else:
                logging.error(f"Failed to publish completion message: {result.rc}")
        else:
            # Publish error message
            error_msg = {
                "status": "error",
                "url": url,
                "name": filename,
                "message": "Failed to download file",
                "timestamp": timestamp,
                "receive_time": receive_time,
            }
            result = client.publish(
                config["topic_publish"],
                json.dumps(error_msg, ensure_ascii=False),
                qos=config["qos"],
            )
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logging.info(f"Published error message for {url}")
            else:
                logging.error(f"Failed to publish error message: {result.rc}")

    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")


def message_processor(client, userdata, stop_event):
    """
    工作线程，用于顺序处理队列中的消息。
    """
    message_queue = userdata["message_queue"]
    config = userdata["config"]
    aria2c_server = userdata["aria2server"]

    while not stop_event.is_set():
        try:
            # Get message from queue (block until a message is available or timeout)
            msg, receive_time = message_queue.get(timeout=1.0)
            logging.info("Dequeued message for processing")
            process_message(client, config, aria2c_server, msg, receive_time)
            message_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logging.error(f"Error in message processor: {str(e)}")


def on_log(client, userdata, paho_log_level, messages):
    """
    MQTT 客户端错误日志。
    """
    if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
        print(messages)


def main():
    service_name = "fetcher"

    # Load configuration
    config = load_config(service_name)

    # Configuration parameters
    BROKER = config["broker"]
    PORT = config["port"]
    QOS = config["qos"]
    KEEPALIVE = config["keepalive"]
    TOPIC_SUBSCRIBE = config["topic_subscribe"]
    TOPIC_PUBLISH = config["topic_publish"]
    suffix = time.strftime(f"_{service_name}_%y%m%d%H%M%S", time.localtime())
    CLIENT_ID = config["client_id"] + suffix
    DOWNLOAD_SAVE_DIR = config["download_save_dir"]
    DOWNLOAD_WEB_URL = config["download_web_url"]
    USERNAME = config.get("username", None)
    PASSWORD = config.get("password", None)

    # Ensure download directory exists
    if not os.path.exists(DOWNLOAD_SAVE_DIR):
        os.makedirs(DOWNLOAD_SAVE_DIR)

    # Setup logging
    setup_logging("fetcher")

    # Print configuration
    print("::Configuration loaded::")
    print(f"MQTT Broker: {BROKER}:{PORT}")
    print(f"QoS Level: {QOS}")
    print(f"Subscribe Topic: {TOPIC_SUBSCRIBE}")
    print(f"Publish Topic: {TOPIC_PUBLISH}")
    print(f"Delete Topic: {config.get('topic_delete', 'N/A')}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Download Directory: {DOWNLOAD_SAVE_DIR}")
    print(f"Download Web URL: {DOWNLOAD_WEB_URL}")
    print()

    # Create message queue and stop event
    message_queue = queue.Queue()
    stop_event = threading.Event()

    # 是否需要启动 aria2c 服务器
    aria2c_server = None
    if config.get("aria2_rpc_enable", False):
        aria2c_server = Aria2cServer(
            host=config.get("aria2_rpc_host", "127.0.0.1"),
            port=config.get("aria2_rpc_port", 6800),
            secret=config.get("aria2_rpc_token", ""),
            save_dir=config.get("aria2_download_dir", "downloads"),
        )
        aria2c_server.start()

    # Prepare userdata
    userdata = {
        "config": config,
        "message_queue": message_queue,
        "aria2server": aria2c_server,
    }

    # Create MQTT client
    mqttc = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, userdata=userdata
    )
    mqttc.reconnect_delay_set(min_delay=1, max_delay=120)

    # Set username and password if provided
    if USERNAME and PASSWORD:
        mqttc.username_pw_set(USERNAME, PASSWORD)
        logging.info(f"Using MQTT authentication: username={USERNAME}")

    # Set callbacks
    mqttc.on_log = on_log
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message

    # Start message processor thread
    processor_thread = threading.Thread(
        target=message_processor, args=(mqttc, userdata, stop_event), daemon=True
    )
    processor_thread.start()

    try:
        # Connect to MQTT broker
        mqttc.connect(BROKER, PORT, keepalive=KEEPALIVE)
        logging.info(f"Connecting to MQTT broker: {BROKER}:{PORT}")
        mqttc.loop_start()  # Start MQTT loop in background thread
        while True:
            time.sleep(1)  # Keep main thread alive
    except KeyboardInterrupt:
        logging.info("Received shutdown signal, stopping...")
        stop_event.set()  # Signal the processor thread to stop
    except Exception as e:
        logging.error(f"Failed to connect or run MQTT client: {e}")
        raise
    finally:
        aria2c_server.stop()
        stop_event.set()  # Ensure processor thread stops
        mqttc.loop_stop()  # Stop MQTT loop
        mqttc.disconnect()  # Disconnect MQTT client
        processor_thread.join()  # Wait for processor thread to finish
        logging.info("MQTT client stopped.")


if __name__ == "__main__":
    print("Starting MQTT file fetcher client...")
    main()
