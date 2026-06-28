# Docker 部署

## Docker Compose
- [`compose.yml`](compose.yml)

### Docker Hub
```yaml
services:
  file-downloader:
    image: idev-sig/file-downloader:latest
    container_name: file-downloader
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
      - MQTT_URL="tcp://test.mosquitto.org:1883"
      - USERNAME=""
      - PASSWORD=""
      - QOS=2
      - KEEPALIVE=60
      - TOPIC_SUBSCRIBE="file/download/request"
      - TOPIC_PUBLISH="file/download/complete"
      - CLIENT_ID="file"
      - DOWNLOAD_SAVE_DIR="downloads"
      - DOWNLOAD_WEB_URL=""
    volumes:
      - ./downloads:/app/downloads
```
