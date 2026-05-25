import subprocess
import os
import time
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import sys

def gopro_usb_copy_latest_logic():
    """
    透過 PowerShell 存取 Windows Shell Namespace (MTP)，
    依據「建立日期」找出最新的影片並複製到 video_output。
    修正了 DateTime 轉換錯誤，改用手動解析。
    """
    GOPRO_DEVICE_NAME_MATCH = "HERO|GoPro"
    
    ps_template = r"""
    try {
        $shell = New-Object -ComObject Shell.Application
        $thisPC = $shell.Namespace(17)
        $gopro = $thisPC.Items() | Where-Object { $_.Name -match "GOPRO_MATCH_TOKEN" }
        if (!$gopro) { throw "找不到 GoPro 裝置，請確認 USB 已連線。" }
        
        $storage = $gopro.GetFolder.Items() | Where-Object { $_.Name -match "GoPro MTP" -or $_.Name -match "Internal Storage" -or $_.Name -match "存儲" -or $_.Name -match "SD Card" }
        if (!$storage) { throw "找不到存儲空間 (SD卡)。" }
        
        $dcim = $storage.GetFolder.Items() | Where-Object { $_.Name -eq "DCIM" }
        if (!$dcim) { throw "找不到 DCIM 資料夾。" }
        
        $goproFolders = $dcim.GetFolder.Items() | Where-Object { $_.Name -match "GOPRO" }
        
        $allFiles = @()
        foreach ($folderItem in $goproFolders) {
            $folder = $folderItem.GetFolder
            
            # 尋找「建立日期」的屬性索引
            $dateCreatedIndex = -1
            for ($i=0; $i -lt 100; $i++) {
                $colName = $folder.GetDetailsOf($null, $i)
                if ($colName -eq "建立日期" -or $colName -eq "Date created") {
                    $dateCreatedIndex = $i
                    break
                }
            }
            if ($dateCreatedIndex -eq -1) { $dateCreatedIndex = 4 }

            $files = $folderItem.GetFolder.Items() | Where-Object { $_.Name -like "*.MP4" }
            foreach ($f in $files) {
                $createDateStr = $folder.GetDetailsOf($f, $dateCreatedIndex)
                if ($createDateStr) {
                    $cleanDateStr = $createDateStr.Replace("?", "").Trim()
                    $sortKey = ""
                    
                    try {
                        # 💡 核心修復：改用 try-catch 與類型轉換，避開 TryParse 的引數問題
                        $dt = [datetime]$cleanDateStr
                        $sortKey = $dt.ToString("yyyyMMddHHmmss")
                    } catch {
                        # 備援解析：手動提取數字
                        $matches = [regex]::Matches($cleanDateStr, "\d+")
                        if ($matches.Count -ge 5) {
                            $year  = $matches[0].Value
                            $month = $matches[1].Value.PadLeft(2, '0')
                            $day   = [int]$matches[2].Value.PadLeft(2, '0')
                            $hour  = $matches[3].Value.PadLeft(2, '0')
                            $min   = $matches[4].Value.PadLeft(2, '0')
                            $sec   = if ($matches.Count -ge 6) { $matches[5].Value.PadLeft(2, '0') } else { "00" }
                            
                            # 處理 上午/下午
                            if ($cleanDateStr -match "下午|PM") {
                                $h_int = [int]$hour
                                if ($h_int -lt 12) { $hour = ($h_int + 12).ToString().PadLeft(2, '0') }
                            } elseif ($cleanDateStr -match "上午|AM") {
                                if ($hour -eq "12") { $hour = "00" }
                            }
                            $sortKey = "$year$month$day$hour$min$sec"
                        } else {
                            $sortKey = $cleanDateStr
                        }
                    }
                    
                    $allFiles += [PSCustomObject]@{
                        Item    = $f
                        SortKey = $sortKey
                        RawDate = $cleanDateStr
                        Name    = $f.Name
                    }
                }
            }
        }
        
        if ($allFiles.Count -eq 0) { throw "在 GoPro 中找不到任何 MP4 影片。" }
        
        # 依據 SortKey 降冪排序，取得最新檔案
        $latest = $allFiles | Sort-Object SortKey -Descending | Select-Object -First 1
        $latestFile = $latest.Item
        
        Write-Host "🎬 偵測到最新影片: $($latest.Name) (建立日期: $($latest.RawDate))"
        
        $destPath = Join-Path (Get-Location) "video_output"
        if (!(Test-Path $destPath)) { New-Item -ItemType Directory -Path $destPath }
        
        $destFolder = $shell.Namespace($destPath)
        
        # CopyHere 16 代表自動覆蓋
        $destFolder.CopyHere($latestFile, 16)
        
        # 等待檔案出現在目標路徑
        $targetFile = Join-Path $destPath $latest.Name
        $timeout = 0
        while (!(Test-Path $targetFile) -and $timeout -lt 60) { 
            Start-Sleep -Seconds 1 
            $timeout++
        }
        
        if (Test-Path $targetFile) {
            Write-Host "SUCCESS:$($latest.Name)"
        } else {
            throw "複製逾時，檔案未出現在目標資料夾。"
        }
    } catch {
        Write-Host "ERROR:$($_.Exception.Message)"
    }
    """
    
    ps_script = ps_template.replace("GOPRO_MATCH_TOKEN", GOPRO_DEVICE_NAME_MATCH)
    
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding='cp950'
        )
        output = result.stdout.strip()
        if "SUCCESS:" in output:
            fname = output.split("SUCCESS:")[1]
            log_msg = f"✅ 傳輸成功！"
            for line in output.split('\n'):
                if "偵測到最新影片" in line:
                    log_msg = f"{line}\n{log_msg}"
            return True, log_msg
        elif "ERROR:" in output:
            return False, f"❌ 失敗: {output.split('ERROR:')[1]}"
        else:
            return False, f"❌ 傳輸異常，請確認 USB 已連線並處於 MTP 模式。"
    except Exception as e:
        return False, f"❌ 執行過程中出錯: {e}"

# ---------- PyQt5 介面封裝 ----------

class USBTransferWorker(QThread):
    finished_signal = pyqtSignal(bool, str)
    def run(self):
        success, message = gopro_usb_copy_latest_logic()
        self.finished_signal.emit(success, message)

class GoProUSBApp(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
    def init_ui(self):
        self.setWindowTitle("GoPro USB 下載工具 (修正 DateTime 版)")
        self.setMinimumSize(500, 450)
        layout = QVBoxLayout()
        self.status_label = QLabel("狀態: 準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        layout.addWidget(self.status_label)
        self.btn_transfer = QPushButton("🚀 依「建立日期」下載最新影片")
        self.btn_transfer.setFixedHeight(60)
        self.btn_transfer.setStyleSheet("background-color: #cce5ff; font-weight: bold; font-size: 14px;")
        self.btn_transfer.clicked.connect(self.start_transfer)
        layout.addWidget(self.btn_transfer)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #f8f9fa; font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.log_view)
        self.setLayout(layout)
    def log(self, message):
        self.log_view.append(message)
    def start_transfer(self):
        self.btn_transfer.setEnabled(False)
        self.log("正在分析 GoPro 內容，請稍候...")
        self.status_label.setText("狀態: 傳輸中...")
        self.worker = USBTransferWorker()
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()
    def on_finished(self, success, message):
        self.log(message)
        self.status_label.setText("狀態: 處理完成")
        self.btn_transfer.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GoProUSBApp()
    window.show()
    sys.exit(app.exec_())
