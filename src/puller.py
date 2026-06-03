import paho.mqtt.client as mqtt
import json
import subprocess
import time
import logging
import queue
import threading
import aria2p
from aria2s import Aria2cServer
from logger import setup_logging
from config import load_config
from utils import extract_url_from_text, is_valid_magnet_url

"""
下载文件到本地的命令行客户端
"""

def on_connect(client, userdata, flags, rc, *args, **kwargs):
    """MQTT 连接回调函数，兼容 MQTT 3.1/3.1.1 和 5.0"""
    logging.info(f"Connected to MQTT broker with result code {rc}")
    if rc == 0:
        # 从 userdata 获取配置
        config = userdata['config']
        client.subscribe(config['topic_subscribe'], qos=config['qos'])
        logging.info(f"Subscribed to topic: {config['topic_subscribe']} with QoS {config['qos']}")
    else:
        logging.error(f"Failed to connect to MQTT broker: {rc}")

def on_message(client, userdata, msg):
    """MQTT 消息回调函数"""
    logging.info(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
    try:
        # Add message to the queue
        userdata['message_queue'].put((msg, time.time()))
        logging.info(f"Message queued for processing: {msg.payload.decode()}")
    except Exception as e:
        logging.error(f"Error queuing message: {str(e)}")

def download_file(download_url, config):
    """
    下载文件
    """
    if config['aria2_rpc_enable']:
        return download_file_aria2_rpc(download_url, config)
    else:
        return download_file_aria2c_cmd(download_url, config)

def download_file_aria2_rpc(download_url, config):
    """
    使用 aria2 RPC 下载文件
    依赖 aria2c --enable-rpc
    """
    logging.info(f"Downloading file using aria2 RPC: {download_url}")
    try:
        save_dir = config.get('aria2_download_dir', 'aria_downloads')
        aria2server = Aria2cServer(
            host=config.get('aria2_rpc_host', '127.0.0.1'),
            port=config.get('aria2_rpc_port', 6800),
            secret=config.get('aria2_rpc_token', ''),
            save_dir=save_dir,
        )

        # 添加下载任务
        aria2 = aria2p.API(aria2server.client(timeout=30))
        options = {'dir': aria2server._real_save_dir(save_dir)}
        download = aria2.add_uris([download_url], options=options)
        logging.info(f"Download added: {download.gid}")

        # 轮询等待下载完成
        max_wait_time = config.get('download_timeout', 3600)  # 默认1小时超时
        waited_time = 0
        last_progress = -1
        retry_count = 0
        max_retries = 3

        # 小文件可能瞬间完成，先检查一次
        try:
            download.update()
            if download.is_complete:
                logging.info(f"Download completed (small file): {download.name}")
                return True
            if download.has_failed:
                logging.error(f"Download failed: {download.error_message}")
                return None
        except Exception as e:
            logging.warning(f"Initial update failed: {str(e)}")

        logging.info(f"Waiting for download to complete...")

        while waited_time < max_wait_time:
            try:
                download.update()
                retry_count = 0  # 重置重试计数

                if download.is_complete:
                    logging.info(f"Download completed: {download.name}")
                    return True

                if download.has_failed:
                    logging.error(f"Download failed: {download.error_message}")
                    return None

                # 记录下载进度（避免重复日志）
                progress = download.progress
                if int(progress) != last_progress and int(progress) % 10 == 0:
                    logging.info(f"Download progress: {progress:.1f}% - {download.name}")
                    last_progress = int(progress)

                # 每30秒记录一次等待状态（避免日志过多）
                if waited_time > 0 and waited_time % 30 == 0:
                    logging.info(f"Still waiting... ({waited_time}s elapsed, progress: {progress:.1f}%)")

            except Exception as e:
                retry_count += 1
                logging.warning(f"RPC update failed (retry {retry_count}/{max_retries}): {str(e)}")
                if retry_count >= max_retries:
                    logging.error(f"Max retries reached, giving up update for this cycle")
                    retry_count = 0
                # 继续循环，不退出，因为下载可能仍在进行

            time.sleep(2)
            waited_time += 2

        # 超时处理
        logging.error(f"Download timeout after {max_wait_time}s: {download_url}")
        try:
            download.remove(force=True)
        except:
            pass
        return None

    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        return None

def download_file_aria2c_cmd(download_url, config):
    """
    使用命令行工具下载文件
    依赖 aria2c
    """
    logging.info(f"Downloading file using aria2c: {download_url}")
    try:
        # 你可以根据需要修改命令
        command = [
            'aria2c',
            '-x', '16',
            '-d', config['aria2_download_dir'],
            download_url,
        ]
        
        logging.info(f"Executing command: {' '.join(command)}")
        
        # 执行下载命令
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",          # 添加 encoding 时
            # errors="ignore",           # 忽略非法字符            
            text=True
        )
        
        if result.returncode == 0:
            logging.info("File downloaded successfully")
            return True
        else:
            # 优先使用 stderr，其次使用 stdout
            error_output = result.stderr if result.stderr else result.stdout
            logging.error(f"Failed to download file. Error: {error_output}")
            return None
            
    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        return None


def send_delete_request(client, config, file_path, name=""):
    """
    发送删除请求到 fetcher 服务器
    """
    try:
        topic_delete = config.get("topic_delete")
        if not topic_delete:
            logging.warning("No delete topic configured, skipping delete request")
            return False

        delete_msg = {
            "file_path": file_path,
            "name": name,
            "timestamp": int(time.time()),
        }

        result = client.publish(
            topic_delete,
            json.dumps(delete_msg, ensure_ascii=False),
            qos=config["qos"],
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logging.info(f"Sent delete request for: {file_path}")
            return True
        else:
            logging.error(f"Failed to send delete request: {result.rc}")
            return False

    except Exception as e:
        logging.error(f"Error sending delete request: {str(e)}")
        return False


def process_message(client, config, msg, receive_time):
    """
    处理单个 MQTT 消息。
    """
    try:
        payload = msg.payload.decode('utf-8')
        logging.info(f"Processing message: {payload}")

        # 尝试解析为JSON
        file_path = None
        file_name = ""
        try:
            data = json.loads(payload)
            download_url = data.get('download_url')
            file_path = data.get('file_path')
            file_name = data.get('name', '')
        except json.JSONDecodeError:
            # 如果不是JSON，尝试直接提取URL
            download_url = extract_url_from_text(payload)

        if not download_url:
            logging.warning("No valid URL found in the message")
            return

        if not is_valid_magnet_url(download_url) and not extract_url_from_text(download_url):
            logging.warning(f"Invalid URL: {download_url}")
            return

        logging.info(f"Download URL: {download_url}")

        # 判断是否存在存在 config['download_web_url'] 值，若存在，则将 download_url 域名修改为 download_web_url 这个的域名。
        # 比如 download_url 为 https://a.com/a/a/a.mp4，aria2_download_dir 为 https://b.com 或 https://b.com/ ，那么将此 download_url 改为 https://b.com/a/a/a.mp4
        if config.get('download_web_url') and config['download_web_url'].startswith(('http://', 'https://')):
            from urllib.parse import urlparse

            original_parsed = urlparse(download_url)
            target_base = config['download_web_url'].rstrip('/')
            download_url = target_base + original_parsed.path
            logging.info(f"New Download URL: {download_url}")

        # 下载文件
        download_result = download_file(download_url, config)

        # 下载成功后发送删除请求到 fetcher 服务器
        if download_result is not None and file_path:
            # 检查是否启用删除远程文件功能
            if config.get('delete_remote_file', False):
                logging.info(f"Download successful, sending delete request for: {file_path}")
                send_delete_request(client, config, file_path, file_name)
            else:
                logging.info(f"Download successful, delete_remote_file is disabled, skipping delete request")
        elif file_path:
            logging.warning(f"Download failed, not sending delete request for: {file_path}")

    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")        

def message_processor(client, userdata, stop_event):
    """Worker thread to process messages from the queue sequentially."""
    message_queue = userdata['message_queue']
    config = userdata['config']
    
    while not stop_event.is_set():
        try:
            # Get message from queue (block until a message is available or timeout)
            msg, receive_time = message_queue.get(timeout=1.0)
            logging.info("Dequeued message for processing")
            process_message(client, config, msg, receive_time)
            message_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logging.error(f"Error in message processor: {str(e)}")

def on_log(client, userdata, paho_log_level, messages):
    if paho_log_level == mqtt.LogLevel.MQTT_LOG_ERR:
        print(messages)


def main():
    service_name = 'puller'

    config = load_config(service_name)
    
    # 配置参数
    BROKER = config['broker']
    PORT = config['port']
    QOS = config['qos']
    KEEPALIVE = config['keepalive']
    # MQTT_TOPIC_SUBSCRIBE = config['MQTT_TOPIC_SUBSCRIBE']
    TOPIC_PUBLISH = config['topic_publish']
    # yymmddhhiiss
    suffix = time.strftime(f"_{service_name}_%y%m%d%H%M%S", time.localtime())
    CLIENT_ID = config['client_id'] + suffix
    DOWNLOAD_WEB_URL = config["download_web_url"]

    USERNAME = config.get('username', None)
    PASSWORD = config.get('password', None)

    ARIA2_RPC_ENABLE = config.get('aria2_rpc_enable', False)
    ARIA2_RPC_HOST = config['aria2_rpc_host']
    ARIA2_RPC_PORT = config['aria2_rpc_port']
    ARIA2_RPC_TOKEN = config['aria2_rpc_token']
    ARIA2_DOWNLOAD_DIR = config['aria2_download_dir']

    DELETE_REMOTE_FILE = config.get('delete_remote_file', False)
    DOWNLOAD_TIMEOUT = config.get('download_timeout', 3600)

    # 确保下载目录存在
    # if not os.path.exists(DOWNLOAD_DIR):
    #     os.makedirs(DOWNLOAD_DIR)

    # 设置日志
    setup_logging(service_name)

    # 这里添加你的 MQTT 客户端逻辑
    print("::Configuration loaded::")
    print(f"MQTT Broker: {BROKER}:{PORT}")
    print(f"MQTT Username: {USERNAME}")
    print(f"MQTT Password: {PASSWORD}")
    print(f"QoS Level: {QOS}")
    print(f"Subscribe Topic: {TOPIC_PUBLISH}")
    print(f"Delete Topic: {config.get('topic_delete', 'N/A')}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Download Web URL: {DOWNLOAD_WEB_URL}")
    print(f"ARIA2 RPC Enable: {ARIA2_RPC_ENABLE}")
    print(f"ARIA2 RPC Host: {ARIA2_RPC_HOST}")
    print(f"ARIA2 RPC Port: {ARIA2_RPC_PORT}")
    print(f"ARIA2 RPC Token: {ARIA2_RPC_TOKEN}")
    print(f"ARIA2 Download Dir: {ARIA2_DOWNLOAD_DIR}")
    print(f"Delete Remote File: {DELETE_REMOTE_FILE}")
    print(f"Download Timeout: {DOWNLOAD_TIMEOUT}")
    print()

    config['client_id'] = CLIENT_ID
    config['username'] = USERNAME
    config['password'] = PASSWORD

    # Create message queue and stop event
    message_queue = queue.Queue()
    stop_event = threading.Event()

    # Prepare userdata
    userdata = {
        'config': config,
        'message_queue': message_queue
    }    

    # 创建MQTT客户端
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, userdata=userdata)
    mqttc.reconnect_delay_set(min_delay=1, max_delay=120)

    # 设置用户名和密码
    if USERNAME and PASSWORD:
        mqttc.username_pw_set(USERNAME, PASSWORD)
        logging.info(f"Using MQTT authentication: username={USERNAME}")

    mqttc.on_log = on_log
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message    

    # Start message processor thread
    processor_thread = threading.Thread(
        target=message_processor,
        args=(mqttc, userdata, stop_event),
        daemon=True
    )
    processor_thread.start()    

    try:
        mqttc.connect(BROKER, PORT, keepalive=KEEPALIVE)  # 增加 keepalive
        logging.info(f"Connecting to MQTT broker: {BROKER}:{PORT}")
        mqttc.loop_start()  # 在后台线程运行 MQTT 循环
        while True:
            time.sleep(1)  # 主线程保持运行
    except KeyboardInterrupt:
        logging.info("Received shutdown signal, stopping...")
        stop_event.set()  # Signal the processor thread to stop            
    except Exception as e:
        logging.error(f"Failed to connect or run MQTT client: {e}")
        raise
    finally:
        stop_event.set()  # Ensure processor thread stops
        mqttc.loop_stop()  # Stop MQTT loop
        mqttc.disconnect()  # Disconnect MQTT client
        processor_thread.join()  # Wait for processor thread to finish
        logging.info("MQTT client stopped.")

if __name__ == "__main__":
    print("Starting MQTT file puller client...")
    main()
