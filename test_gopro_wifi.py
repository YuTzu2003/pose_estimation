import asyncio
import socket
import logging
from bleak import BleakClient, BleakScanner
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# GoPro UUIDs
NM_COMMAND_CHAR = "b5f90091-aa8d-11e3-9046-0002a5d5c51b"
WIFI_SSID_UUID = "b5f90002-aa8d-11e3-9046-0002a5d5c51b" # 熱點模式的，我們這裡用來喚醒相機
WAKE_WIFI = bytearray([0x03, 0x17, 0x01, 0x01])
GOPRO_COMMAND_UUID = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"


# ==========================================
# 填寫你的 Wi-Fi 資訊
# ==========================================
TARGET_SSID = "TP-Link_6444"
TARGET_PASS = "nfu123@@@"
# ==========================================


def check_gopro_http(ip):
    """測試特定 IP 是否開放了 GoPro 的 8080 port"""
    try:
        url = f"http://{ip}:8080/gopro/camera/state"
        response = requests.get(url, timeout=1.0)
        if response.status_code == 200:
            return True
    except:
        pass
    return False

def get_local_ip_prefix():
    """偵測目前電腦的 IP 網段"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        prefix = ".".join(ip.split(".")[:-1])
        return prefix, ip
    except:
        return None, None

def scan_network_for_gopro():
    """多執行緒掃描區域網路內可能的 GoPro IP"""
    logger.info("🔍 開始掃描區域網路尋找 GoPro (Port 8080)...")
    
    prefix, local_ip = get_local_ip_prefix()
    if not prefix:
        logger.error("❌ 無法偵測本地 IP，請檢查網路連線。")
        return None
    
    logger.info(f"偵測到本地 IP: {local_ip}，網段: {prefix}.x")
    
    # 定義要掃描的網段列表
    prefixes_to_scan = [prefix]
    
    # 如果偵測到的網段不是常見的 192.168.x.x，且目標是 TP-Link (通常是 192.168.0 或 192.168.1)
    # 我們也額外掃描一下常見網段 (雖然如果不同網段通常連不到，但以防萬一)
    if not prefix.startswith("192.168"):
        logger.warning(f"⚠️ 你的電腦目前 IP ({local_ip}) 看起來不像一般的家用路由器網段。")
        logger.warning(f"如果 GoPro 連接的是 {TARGET_SSID}，請確保你的電腦也連接到同一個 Wi-Fi。")
        prefixes_to_scan.extend(["192.168.0", "192.168.1"])
    
    prefixes_to_scan = list(set(prefixes_to_scan)) # 移除重複
    
    found_ip = None
    for p in prefixes_to_scan:
        logger.info(f"正在掃描網段: {p}.1 ~ {p}.254 ...")
        ips_to_check = [f"{p}.{i}" for i in range(1, 255)]
        
        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = {executor.submit(check_gopro_http, ip): ip for ip in ips_to_check}
            for future in as_completed(futures):
                ip = futures[future]
                if future.result():
                    logger.info(f"✅ 找到 GoPro！IP 位址: {ip}")
                    return ip
    
    logger.warning("❌ 掃描完成，未在區域網路找到 GoPro。")
    return None

# GoPro Status UUIDs
GOPRO_QUERY_CHAR = "b5f90076-aa8d-11e3-9046-0002a5d5c51b"
GOPRO_SUBSCRIBE_CHAR = "b5f90077-aa8d-11e3-9046-0002a5d5c51b"

async def test_gopro_connection():
    logger.info("正在尋找 GoPro 藍牙...")
    devices = await BleakScanner.discover(timeout=5.0)
    gopro = next((d for d in devices if d.name and "GoPro" in d.name), None)

    if not gopro:
        logger.error("❌ 找不到 GoPro 藍牙，請確定相機已開機且未連接 USB。")
        return

    logger.info(f"找到相機: {gopro.name}，嘗試藍牙連線...")
    
    try:
        async with BleakClient(gopro.address) as client:
            logger.info("✅ 藍牙連線成功！")
            
            # 1. 確保 Wi-Fi 模組是喚醒的
            logger.info("發送喚醒 Wi-Fi 指令...")
            try:
                # 0x03, 0x17, 0x01, 0x01 (Enable Wi-Fi)
                await client.write_gatt_char(GOPRO_COMMAND_UUID, bytearray([0x03, 0x17, 0x01, 0x01]), response=True)
            except:
                pass
            await asyncio.sleep(2)

            # 2. 發送 Wi-Fi 憑證 (Station Mode Provisioning)
            logger.info(f"傳送 Wi-Fi 憑證 (SSID: {TARGET_SSID}) 至 GoPro...")
            
            # 構造 COHN payload
            # 0x01: SSID, 0x02: Password
            # 命令格式: [Len, 0x03 (Provisioning), 0x0a, L1, SSID..., 0x12, L2, PASS...]
            payload = bytearray([0x0a, len(TARGET_SSID)]) + TARGET_SSID.encode() + bytearray([0x12, len(TARGET_PASS)]) + TARGET_PASS.encode()
            command = bytearray([len(payload) + 1, 0x03]) + payload
            
            await client.write_gatt_char(NM_COMMAND_CHAR, command, response=True)
            logger.info("✅ 憑證已送達！請觀察相機螢幕是否有 Wi-Fi 連線動畫...")
            
            # 3. 監控連線狀態 (嘗試詢問 10 次)
            logger.info("正在透過藍牙追蹤連線進度...")
            for attempt in range(15):
                # 查詢狀態 69 (Station Connection State)
                # 0x02, 0x13, 0x45 (69)
                await client.write_gatt_char(GOPRO_QUERY_CHAR, bytearray([0x02, 0x13, 0x45]), response=True)
                # 這裡需要監聽通知，但為了簡化，我們直接等待並觀察
                await asyncio.sleep(3)
                print(f"等待連線中 ({attempt+1}/15)...", end="\r")
            print()
            
    except Exception as e:
        logger.error(f"藍牙操作失敗: {e}")
        return

    # 4. 掃描網路
    found_ip = scan_network_for_gopro()
    
    if found_ip:
        logger.info("=========================================")
        logger.info(f"🎉 測試成功！GoPro 已成功連上你的內網。")
        logger.info(f"你可以在主程式的 'GoPro IP' 欄位填入: {found_ip}")
        logger.info("=========================================")
    else:
        logger.error("=========================================")
        logger.error("❌ 測試失敗！GoPro 沒有出現在你的區域網路中。")
        logger.error("可能原因：")
        logger.error("1. 密碼錯誤。")
        logger.error("2. TP-Link_6444 是 5GHz 網路，但 GoPro 較舊型號可能只支援 2.4GHz。")
        logger.error("3. 路由器設定了 AP 隔離，阻止設備互相連線。")
        logger.error("=========================================")

if __name__ == "__main__":
    asyncio.run(test_gopro_connection())
