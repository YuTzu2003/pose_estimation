document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const fileDrop = document.getElementById('fileDrop');
  const imuInput = document.getElementById('imuInput');
  const imuFileNameDisplay = document.getElementById('imuFileName');
  const imuDrop = document.getElementById('imuDrop');
  const uploadForm = document.getElementById('uploadForm');

  if (fileInput && fileNameDisplay) {
    const updateFileName = () => {
      if (fileInput.files.length > 0) {
        fileNameDisplay.textContent = fileInput.files[0].name;
        fileNameDisplay.style.color = 'var(--fg)';
      } else {
        fileNameDisplay.textContent = '未選取';
        fileNameDisplay.style.color = 'var(--muted)';
      }
    };
    fileInput.addEventListener('change', updateFileName);
  }

  if (imuInput && imuFileNameDisplay) {
    const updateImuFileName = () => {
      if (imuInput.files.length > 0) {
        imuFileNameDisplay.textContent = imuInput.files[0].name;
        imuFileNameDisplay.style.color = 'var(--fg)';
      } else {
        imuFileNameDisplay.textContent = '未選取';
        imuFileNameDisplay.style.color = 'var(--muted)';
      }
    };
    imuInput.addEventListener('change', updateImuFileName);
  }

  const setupDropzone = (dropzone, input, callback) => {
    if (!dropzone) return;
    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = 'var(--fg)';
    });
    dropzone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = 'var(--border)';
    });
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = 'var(--border)';
      if (e.dataTransfer.files.length > 0) {
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event('change'));
      }
    });
  };

  setupDropzone(fileDrop, fileInput);
  setupDropzone(imuDrop, imuInput);

  // 全域變數儲存當前分析資訊
  let currentAnalysis = {
    record_id: null,
    peak_data: [],
    scale_info: null,
    person_records: null,
    fps: 30
  };

  if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const hasVideo = fileInput.files.length > 0;
      const hasImu = imuInput.files.length > 0;
      
      if (!hasVideo && !hasImu) {
        alert('請先選擇影片檔案或 IMU 數據檔案');
        return;
      }
      
      const formData = new FormData(uploadForm);
      const jobId = 'job_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
      formData.append('job_id', jobId);
      
      const progressContainer = document.getElementById('progressContainer');
      const progressBar = document.getElementById('progressBar');
      const progressStatus = document.getElementById('progressStatus');
      const progressPercent = document.getElementById('progressPercent');
      const startBtn = document.getElementById('startBtn');

      try {
        startBtn.textContent = '處理中...';
        startBtn.disabled = true;
        
        progressContainer.classList.remove('d-none');
        progressBar.style.width = '0%';
        progressPercent.textContent = '0%';
        progressStatus.textContent = '正在上傳檔案...';

        const pollInterval = setInterval(async () => {
          try {
            const res = await fetch(`/api/progress/${jobId}`);
            if (res.ok) {
              const data = await res.json();
              progressBar.style.width = data.progress + '%';
              progressPercent.textContent = Math.round(data.progress) + '%';
              progressStatus.textContent = data.status || '處理中...';
              if (data.progress >= 100) clearInterval(pollInterval);
            }
          } catch (err) {}
        }, 1000);

        const response = await fetch('/upload', {
          method: 'POST',
          body: formData
        });
        
        clearInterval(pollInterval);
        const result = await response.json();
        
        if (response.ok) {
          progressBar.style.width = '100%';
          progressPercent.textContent = '100%';
          progressStatus.textContent = '處理完成！';
          currentAnalysis.record_id = result.record_id;
          currentAnalysis.peak_data = result.peak_data;
          currentAnalysis.scale_info = {
            reference: document.getElementById('scale_reference').value,
            pixels: document.getElementById('scale_pixels').value
          };
          currentAnalysis.person_records = result.person_records;
          currentAnalysis.fps = result.fps || 30;

          // 更新預覽畫面
          const videoFrame = document.querySelector('.video-frame');
          if (videoFrame) {
            videoFrame.innerHTML = '';
            if (result.video_url) {
                const videoUrl = result.video_url + '?t=' + new Date().getTime();
                videoFrame.innerHTML += `
                  <div class="mb-3">
                    <video id="previewVideo" width="100%" height="auto" controls autoplay style="display: block; width: 100%; height: auto; border-radius: 4px;">
                        <source src="${videoUrl}" type="video/mp4">
                    </video>
                  </div>
                `;
                const speedContainer = document.getElementById('previewSpeedContainer');
                if (speedContainer) speedContainer.classList.remove('d-none');
            }
            if (result.imu_plot_url || result.record_id) {
                const imuUrl = result.imu_plot_url || `/api/imu_plot/${result.record_id}?type=acc_res`;
                videoFrame.innerHTML += `
                  <div class="mt-4 text-center">
                    <h5 class="small text-muted mb-3 mono">IMU ANALYSIS PREVIEW (RESULTANT ACC)</h5>
                    <div class="bg-white p-2 rounded border">
                        <img src="${imuUrl}" class="img-fluid" alt="IMU Plot">
                    </div>
                  </div>
                `;
            }
            videoFrame.classList.remove('d-flex', 'align-items-center', 'justify-content-center', 'text-white-50');
            videoFrame.style.height = 'auto';
            videoFrame.style.minHeight = '0';
            videoFrame.style.background = 'transparent';
            videoFrame.style.border = 'none';
          }

          if (result.peak_data && result.peak_data.length > 0) {
            populatePeakTable(result.peak_data);
          } else {
            document.getElementById('csvBody').innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">此項目無步頻數據</td></tr>';
          }

          const resultSec = document.getElementById('result');
          if (resultSec) resultSec.scrollIntoView({ behavior: 'smooth' });
          setTimeout(() => alert('處理完成！'), 500);
        } else {
          alert('處理失敗: ' + result.error);
        }
      } catch (err) {
        console.error(err);
        alert('發生錯誤，請稍後再試。');
      } finally {
        startBtn.textContent = '開始分析 / START ANALYSIS';
        startBtn.disabled = false;
      }
    });
  }

  function populatePeakTable(peakData) {
    const csvBody = document.getElementById('csvBody');
    if (!csvBody) return;

    if (!peakData || peakData.length === 0) {
      csvBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">目前無步頻數據</td></tr>';
      return;
    }

    let rowsHTML = '';
    peakData.forEach((row) => {
      if (row.Frame_Right !== null) {
        rowsHTML += createRowHTML(row.Frame_Right, row.X_Right, 'Right', row.Y_Right);
      }
      if (row.Frame_Left !== null) {
        rowsHTML += createRowHTML(row.Frame_Left, row.X_Left, 'Left', row.Y_Left);
      }
    });
    
    csvBody.innerHTML = rowsHTML;
    sortAndReindexTable();
  }

  function createRowHTML(frame, x, foot, y) {
    return `
      <tr class="peak-row" data-foot="${foot}">
        <td class="text-muted row-idx"></td>
        <td contenteditable="true" class="mono peak-frame">${frame}</td>
        <td>
          <select class="form-select form-select-sm peak-foot-select" onchange="updateFootBadge(this)">
            <option value="Right" ${foot === 'Right' ? 'selected' : ''}>Right</option>
            <option value="Left" ${foot === 'Left' ? 'selected' : ''}>Left</option>
          </select>
        </td>
        <td contenteditable="true" class="peak-x">${Math.round(x)}</td>
        <td contenteditable="true" class="peak-y">${y ? Math.round(y) : 0}</td>
        <td>
          <button class="btn btn-outline-danger btn-sm" onclick="deleteRow(this)">刪除</button>
        </td>
      </tr>
    `;
  }

  window.updateFootBadge = (el) => {
    const foot = el.value;
    el.closest('tr').setAttribute('data-foot', foot);
  };

  window.deleteRow = (btn) => {
    if (confirm('確定要刪除此步點？')) {
      btn.closest('tr').remove();
      sortAndReindexTable();
    }
  };

  window.addNewPeak = () => {
    const csvBody = document.getElementById('csvBody');
    const newRow = createRowHTML(0, 0, 'Right', 0);
    const tempDiv = document.createElement('tbody');
    tempDiv.innerHTML = newRow;
    csvBody.appendChild(tempDiv.firstElementChild);
    sortAndReindexTable();
  };

  function sortAndReindexTable() {
    const csvBody = document.getElementById('csvBody');
    const rows = Array.from(csvBody.querySelectorAll('.peak-row'));
    if (rows.length === 0) return;

    rows.sort((a, b) => {
      const frameA = parseInt(a.querySelector('.peak-frame').textContent) || 0;
      const frameB = parseInt(b.querySelector('.peak-frame').textContent) || 0;
      return frameA - frameB;
    });

    csvBody.innerHTML = '';
    rows.forEach((row, index) => {
      row.querySelector('.row-idx').textContent = index + 1;
      csvBody.appendChild(row);
    });
  }

  const regenBtn = document.getElementById('regenBtn');
  if (regenBtn) {
    regenBtn.onclick = async () => {
      if (!currentAnalysis.record_id) {
        alert('請先進行影片分析。');
        return;
      }

      const rows = document.querySelectorAll('.peak-row');
      const newPeakData = [];
      let rightPeaks = [];
      let leftPeaks = [];

      rows.forEach(row => {
        const frame = parseInt(row.querySelector('.peak-frame').textContent) || 0;
        const x = parseFloat(row.querySelector('.peak-x').textContent) || 0;
        const y = parseFloat(row.querySelector('.peak-y').textContent) || 0;
        const foot = row.getAttribute('data-foot');

        if (foot === 'Right') {
          rightPeaks.push({ Frame: frame, X: x, Y: y });
        } else {
          leftPeaks.push({ Frame: frame, X: x, Y: y });
        }
      });

      const maxLen = Math.max(rightPeaks.length, leftPeaks.length);
      for (let i = 0; i < maxLen; i++) {
        newPeakData.push({
          Frame_Right: rightPeaks[i] ? rightPeaks[i].Frame : null,
          X_Right: rightPeaks[i] ? rightPeaks[i].X : null,
          Y_Right: rightPeaks[i] ? rightPeaks[i].Y : null,
          Frame_Left: leftPeaks[i] ? leftPeaks[i].Frame : null,
          X_Left: leftPeaks[i] ? leftPeaks[i].X : null,
          Y_Left: leftPeaks[i] ? leftPeaks[i].Y : null
        });
      }

      try {
        regenBtn.textContent = '產出中...';
        regenBtn.disabled = true;

        const response = await fetch('/regenerate_gait', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            record_id: currentAnalysis.record_id,
            peak_data: newPeakData,
            scale_info: currentAnalysis.scale_info,
            person_records: currentAnalysis.person_records
          })
        });

        const result = await response.json();
        if (response.ok) {
          const videoFrame = document.querySelector('.video-frame');
          if (videoFrame && result.video_url) {
            const videoUrl = result.video_url + (result.video_url.includes('?') ? '&' : '?') + 't=' + new Date().getTime();
            videoFrame.innerHTML = `
              <video id="previewVideo" width="100%" height="auto" controls autoplay style="display: block; width: 100%; height: auto; border-radius: 4px;">
                <source src="${videoUrl}" type="video/mp4">
                您的瀏覽器不支援影片播放。
              </video>
            `;
            videoFrame.style.height = 'auto';
            videoFrame.style.minHeight = '0';
            videoFrame.style.background = 'transparent';
            videoFrame.style.border = 'none';
            videoFrame.classList.remove('d-flex', 'align-items-center', 'justify-content-center', 'text-white-50');

            // Apply current playback speed
            const speedSelector = document.getElementById('previewSpeed');
            const previewVideo = document.getElementById('previewVideo');
            if (speedSelector && previewVideo) {
                previewVideo.playbackRate = parseFloat(speedSelector.value);
            }

            // 更新下載連結
            const downloadBtn = document.querySelector('a[href*="/static/jobs/"][class*="btn-dark"], a[href="#"][class*="btn-dark"]');
            if (downloadBtn) {
              downloadBtn.href = videoUrl;
              downloadBtn.download = result.video_url.split('/').pop().split('?')[0];
            }
            // 同時更新 Gait CSV 下載連結 (加上 timestamp 避免快取)
            const csvBtns = document.querySelectorAll('a[class*="btn-outline-dark"][download*="_peaks.csv"]');
            if (csvBtns.length > 0) {
              const currentHref = csvBtns[0].href.split('?')[0];
              csvBtns[0].href = `${currentHref}?t=${new Date().getTime()}`;
            }
          }
          alert('影片已重新生成！');
        } else {
          alert('重新生成失敗: ' + result.error);
        }
      } catch (err) {
        console.error(err);
        alert('發生錯誤');
      } finally {
        regenBtn.textContent = '重新產生影片';
        regenBtn.disabled = false;
      }
    };
  }

  const saveProjectBtn = document.getElementById('saveProjectBtn');
  if (saveProjectBtn) {
    saveProjectBtn.onclick = () => {
      if (!currentAnalysis.record_id) {
        alert('請先上傳影片並完成分析後再保存。');
        return;
      }
      
      const sessionName = document.getElementById('session').value || "未指定場次";
      
      // Call the LINE notification API
      fetch('/api/line_notify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          record_id: currentAnalysis.record_id,
          session_name: sessionName
        })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          alert('專案已完整保存，並已發送 LINE 通知！\n紀錄 ID: ' + currentAnalysis.record_id);
        } else {
          console.error('LINE notification failed:', data.error);
          alert('專案已保存，但 LINE 通知發送失敗。\n紀錄 ID: ' + currentAnalysis.record_id);
        }
      })
      .catch(err => {
        console.error('Error sending LINE notification:', err);
        alert('專案已保存，但發送通知時發生錯誤。\n紀錄 ID: ' + currentAnalysis.record_id);
      });
    };
  }

  const csvBodyInner = document.getElementById('csvBody');
  if (csvBodyInner && csvBodyInner.innerHTML.trim() === '') {
    csvBodyInner.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">請先上傳影片進行分析</td></tr>';
  }

  // Preview speed control
  const previewSpeed = document.getElementById('previewSpeed');
  if (previewSpeed) {
    previewSpeed.addEventListener('change', () => {
      const previewVideo = document.getElementById('previewVideo');
      if (previewVideo) {
        previewVideo.playbackRate = parseFloat(previewSpeed.value);
      }
    });
  }
});
