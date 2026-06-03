import os
import platform
import re
import time
from urllib.parse import urlparse

def extract_url_from_text(text):
    """从文本中提取URL。"""
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    match = url_pattern.search(text)
    return match.group(0) if match else None

def is_valid_m3u8_url(url):
    """验证URL是否为有效的M3U8 URL。"""
    try:
        url_obj = urlparse(url)
        return all([url_obj.scheme, url_obj.netloc]) and url_obj.path.endswith('.m3u8')
    except ValueError:
        return False
    
def is_valid_mp4_url(url):
    """验证URL是否为有效的MP4 URL。"""
    try:
        url_obj = urlparse(url)
        return all([url_obj.scheme, url_obj.netloc]) and url_obj.path.endswith('.mp4')
    except ValueError:
        return False    

def is_valid_magnet_url(url):
    """验证URL是否为有效的磁力链接。"""
    return url.startswith('magnet:')

def get_file_suffix(url):
    """从URL中获取文件后缀。"""
    return os.path.splitext(url)[-1]

def truncate_filename(filename: str, max_bytes=230) -> str:
    """
    将文件名截断以适应最大字节限制，正确处理中文、日文等多字节字符。
    
    Args:
        filename: 原始文件名
        max_bytes: 最大字节数限制（默认230，为255留出一些缓冲）
    
    Returns:
        截断后的安全文件名
    """
    if not filename:
        timestamp = int(time.time())
        return f"file_{timestamp}"
    
    # 移除文件名中的非法字符
    filename = sanitize_filename(filename)
    
    # 如果清理后文件名为空，使用默认名称
    if not filename:
        timestamp = int(time.time())
        return f"file_{timestamp}"
    
    # 拆分文件名和扩展名
    name, ext = os.path.splitext(filename)

    # 检测扩展名是否合理（短且是字母数字），不合理则当作无扩展名
    # 避免把 "19.5" 中的 "." 当作扩展名分隔符
    if ext and (len(ext) > 10 or not re.match(r'^\.[a-zA-Z0-9]+$', ext)):
        name = filename
        ext = ''
    
    system = platform.system()
    
    if system == 'Windows':
        # Windows: 文件名最大255字符，路径最大260字符
        max_chars = 255 - len(ext)
        if len(filename) <= 255:
            return filename
        return name[:max_chars] + ext
    
    elif system == 'Darwin':  # macOS
        # macOS: 文件名最大255 UTF-8字节
        max_name_bytes = 255 - len(ext.encode('utf-8'))
        return _truncate_by_bytes(name, ext, max_name_bytes)
    
    else:  # Linux 和其他 Unix 系统
        # Linux/ext4: 文件名最大255字节
        max_name_bytes = max_bytes - len(ext.encode('utf-8'))
        return _truncate_by_bytes(name, ext, max_name_bytes)


def _truncate_by_bytes(name: str, ext: str, max_name_bytes: int) -> str:
    """
    按字节数截断文件名，确保不会截断多字节字符的中间。
    """
    if max_name_bytes <= 0:
        return ext  # 如果扩展名太长，只返回扩展名
    
    name_bytes = name.encode('utf-8')
    
    if len(name_bytes) <= max_name_bytes:
        return name + ext
    
    # 从最大字节数开始向前查找，找到完整的UTF-8字符边界
    truncated_bytes = name_bytes[:max_name_bytes]
    
    # 向前查找完整的UTF-8字符边界
    while len(truncated_bytes) > 0:
        try:
            safe_name = truncated_bytes.decode('utf-8')
            return safe_name + ext
        except UnicodeDecodeError:
            # 如果解码失败，说明截断在字符中间，向前退一个字节
            truncated_bytes = truncated_bytes[:-1]
    
    # 如果所有字节都无法解码（理论上不应该发生），返回扩展名
    return ext


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除或替换非法字符。
    
    Args:
        filename: 原始文件名
    
    Returns:
        清理后的文件名
    """
    # Windows 非法字符: < > : " | ? * \ /
    # 以及控制字符 (ASCII 0-31)
    illegal_chars = r'[<>:"|?*\\/]'
    
    # 替换非法字符为下划线
    cleaned = re.sub(illegal_chars, '_', filename)
    
    # 移除控制字符
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', cleaned)
    
    # 移除开头和结尾的空格和点号
    cleaned = cleaned.strip(' .')
    
    # 如果文件名为空或只有扩展名，使用默认名称
    if not cleaned or cleaned.startswith('.'):
        timestamp = int(__import__('time').time())
        cleaned = f"file_{timestamp}" + (cleaned if cleaned.startswith('.') else '')
    
    return cleaned