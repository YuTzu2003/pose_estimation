document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const fileDrop = document.getElementById('fileDrop');
  const uploadForm = document.getElementById('uploadForm');

  if (fileInput && fileNameDisplay) {
    const updateFileName = () => {
      if (fileInput.files.length > 0) {
        fileNameDisplay.textContent = fileInput.files[0].name;
        fileNameDisplay.style.color = 'var(--fg)';
      } else {
        fileNameDisplay.textContent = '未選取檔案';
        fileNameDisplay.style.color = 'var(--muted)';
      }
    };

    fileInput.addEventListener('change', updateFileName);
    updateFileName(); // Initial check
  }

  if (fileDrop) {
    fileDrop.addEventListener('dragover', (e) => {
      e.preventDefault();
      fileDrop.style.borderColor = 'var(--fg)';
    });
    fileDrop.addEventListener('dragleave', (e) => {
      e.preventDefault();
      fileDrop.style.borderColor = 'var(--border)';
    });
    fileDrop.addEventListener('drop', (e) => {
      e.preventDefault();
      fileDrop.style.borderColor = 'var(--border)';
      if (e.dataTransfer.files.length > 0) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
  }

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
      
      const file = fileInput.files[0];
      if (!file) {
        alert('請先選擇要上傳的影片檔案');
        return;
      }
      
      const formData = new FormData(uploadForm);
      
      try {
        const btn = uploadForm.querySelector('button[type="submit"]');
        btn.textContent = '分析中...';
        btn.disabled = true;

        const response = await fetch('/upload', {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
          currentAnalysis.record_id = result.record_id;
          currentAnalysis.peak_data = result.peak_data;
          currentAnalysis.scale_info = result.scale_info;
          currentAnalysis.person_records = result.person_records;
          currentAnalysis.fps = result.fps || 30;

          // 更新預覽畫面顯示分析後的影片
          const videoFrame = document.querySelector('.video-frame');
          if (videoFrame && result.video_url) {
            const videoUrl = result.video_url + '?t=' + new Date().getTime();
            videoFrame.innerHTML = `
              <video width="100%" height="auto" controls autoplay style="display: block; max-height: 70vh; object-fit: contain;">
                <source src="${videoUrl}" type="video/mp4">
                您的瀏覽器不支援影片播放。
              </video>
            `;
            videoFrame.classList.remove('d-flex', 'align-items-center', 'justify-content-center', 'text-white-50');
            videoFrame.style.height = 'auto';
            videoFrame.style.minHeight = '0';
            videoFrame.style.background = 'black';

            // 更新下載連結
            const downloadBtn = document.querySelector('a[href="#"][class*="btn-dark"]');
            if (downloadBtn) {
              downloadBtn.href = videoUrl;
              downloadBtn.download = result.video_url.split('/').pop();
            }
            const csvBtns = document.querySelectorAll('a[href="#"][class*="btn-outline-dark"]');
            if (csvBtns.length >= 2) {
              if (result.pose_csv) {
                csvBtns[0].href = '/static/' + result.pose_csv;
                csvBtns[0].download = result.pose_csv.split('/').pop();
              }
              // Gait CSV 可能是之後生成的，這裡我們先填入路徑
              if (result.record_id) {
                csvBtns[1].href = `/static/jobs/${result.record_id}/${result.record_id}_peaks.csv`;
                csvBtns[1].download = `${result.record_id}_peaks.csv`;
              }
            }
          }

          populatePeakTable(result.peak_data);

          const resultSec = document.getElementById('result');
          if (resultSec) resultSec.scrollIntoView({ behavior: 'smooth' });
          
          setTimeout(() => alert('分析完成！'), 500);
        } else {
          alert('分析失敗: ' + result.error);
        }
      } catch (err) {
        console.error(err);
        alert('上傳過程發生錯誤，請稍後再試。');
      } finally {
        const btn = uploadForm.querySelector('button[type="submit"]');
        btn.textContent = '開始分析';
        btn.disabled = false;
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
              <video width="100%" height="auto" controls autoplay style="display: block; max-height: 70vh; object-fit: contain;">
                <source src="${videoUrl}" type="video/mp4">
                您的瀏覽器不支援影片播放。
              </video>
            `;
            videoFrame.style.height = 'auto';
            videoFrame.style.minHeight = '0';
            videoFrame.style.background = 'black';
            videoFrame.classList.remove('d-flex', 'align-items-center', 'justify-content-center', 'text-white-50');

            // 更新下載連結
            const downloadBtn = document.querySelector('a[href*="/static/jobs/"][class*="btn-dark"], a[href="#"][class*="btn-dark"]');
            if (downloadBtn) {
              downloadBtn.href = videoUrl;
              downloadBtn.download = result.video_url.split('/').pop().split('?')[0];
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
        regenBtn.textContent = '重新生成影片';
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
      alert('專案已完整保存！\n紀錄 ID: ' + currentAnalysis.record_id);
    };
  }

  const csvBodyInner = document.getElementById('csvBody');
  if (csvBodyInner && csvBodyInner.innerHTML.trim() === '') {
    csvBodyInner.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">請先上傳影片進行分析</td></tr>';
  }
});
