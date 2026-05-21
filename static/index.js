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
        const originalText = btn.textContent;
        btn.textContent = '上傳中...';
        btn.disabled = true;

        const response = await fetch('/upload', {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
          // 更新預覽畫面顯示分析後的影片
          const videoFrame = document.querySelector('.video-frame');
          if (videoFrame && result.video_url) {
            // 加入時間戳記避免瀏覽器快取舊影片
            const videoUrl = result.video_url + '?t=' + new Date().getTime();
            videoFrame.innerHTML = `
              <video width="100%" height="auto" controls autoplay>
                <source src="${videoUrl}" type="video/mp4">
                您的瀏覽器不支援影片播放。
              </video>
            `;
            videoFrame.classList.remove('d-flex', 'align-items-center', 'justify-content-center', 'text-white-50');
            videoFrame.style.height = 'auto';
            videoFrame.style.background = 'black';
          }

          const resultSec = document.getElementById('result');
          if (resultSec) resultSec.scrollIntoView({ behavior: 'smooth' });
          
          // 最後才顯示完成訊息
          setTimeout(() => alert('分析完成！'), 500);
        } else {
          alert('上傳失敗: ' + result.error);
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

  // Mock CSV data generation
  const csvBody = document.getElementById('csvBody');
  if (csvBody) {
    let rowsHTML = '';
    for (let i = 184; i <= 188; i++) {
      const time = (i / 60).toFixed(2);
      const foot = i % 2 === 0 ? 'L' : 'R';
      const stride = (2.10 + Math.random() * 0.1).toFixed(2);
      const speed = (6.50 + Math.random() * 0.2).toFixed(2);
      const conf = (0.85 + Math.random() * 0.1).toFixed(2);
      const confColor = conf > 0.9 ? 'text-success' : 'text-warning';
      
      rowsHTML += `
        <tr>
          <td class="text-muted">${i - 183}</td>
          <td class="mono">${i}</td>
          <td class="mono">${time}</td>
          <td><span class="badge bg-light text-dark border">${foot}</span></td>
          <td contenteditable="true" class="bg-white border" style="cursor:text">${stride}</td>
          <td contenteditable="true" class="bg-white border" style="cursor:text">${speed}</td>
          <td class="mono ${confColor}">${(conf * 100).toFixed(1)}%</td>
        </tr>
      `;
    }
    csvBody.innerHTML = rowsHTML;
  }
});
