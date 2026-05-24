document.addEventListener('DOMContentLoaded', () => {
  // --- 1. State & Global Variables ---
  let currentAnalysis = {
    record_id: null,
    peak_data: [],
    scale_info: null,
    person_records: null,
    fps: 30
  };

  const autoMeasureBtn = document.getElementById('autoMeasureBtn');
  const scalePreset = document.getElementById('scalePreset');
  const scaleRefInput = document.getElementById('scale_reference');
  const scalePxInput = document.getElementById('scale_pixels');
  const presetInfo = document.getElementById('presetInfo');

  const toggleAutoMeasureBtn = () => {
    if (autoMeasureBtn && scalePreset) {
      const hasLocalFile = fileInput && fileInput.files.length > 0;
      if (scalePreset.value === 'custom' && (currentAnalysis.record_id || hasLocalFile)) {
        autoMeasureBtn.style.display = 'inline-block';
      } else {
        autoMeasureBtn.style.display = 'none';
      }
    }
  };

  // --- 2. UI Components & Event Listeners ---
  const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
  popoverTriggerList.map(function (popoverTriggerEl) { return new bootstrap.Popover(popoverTriggerEl) })

  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const fileDrop = document.getElementById('fileDrop');
  const imuInput = document.getElementById('imuInput');
  const imuFileNameDisplay = document.getElementById('imuFileName');
  const imuDrop = document.getElementById('imuDrop');
  const uploadForm = document.getElementById('uploadForm');

  if (fileInput && fileNameDisplay) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        fileNameDisplay.textContent = fileInput.files[0].name;
        fileNameDisplay.style.color = 'var(--fg)';
      } else {
        fileNameDisplay.textContent = '未選取';
        fileNameDisplay.style.color = 'var(--muted)';
      }
      toggleAutoMeasureBtn();
    });
  }

  const setupDropzone = (dropzone, input) => {
    if (!dropzone) return;
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.style.borderColor = 'var(--fg)'; });
    dropzone.addEventListener('dragleave', (e) => { e.preventDefault(); dropzone.style.borderColor = 'var(--border)'; });
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

  const calibrationPresets = {
    preset1: {
      ref_dist: 0.9,
      pixels: 221,
      description: "攝影機離跑道: 5.85m | 高度: 1.02m | 垂直角距離: 1m"
    }
  };

  if (scalePreset) {
    scalePreset.addEventListener('change', () => {
      const val = scalePreset.value;
      if (val === 'custom') {
        presetInfo.classList.add('d-none');
        scaleRefInput.readOnly = false;
        scalePxInput.readOnly = false;
      } else if (calibrationPresets[val]) {
        const p = calibrationPresets[val];
        scaleRefInput.value = p.ref_dist;
        scalePxInput.value = p.pixels;
        scaleRefInput.readOnly = true;
        scalePxInput.readOnly = true;
        presetInfo.innerHTML = `<i class="bi bi-info-circle me-1"></i>配置詳情: ${p.description}`;
        presetInfo.classList.remove('d-none');
      }
      toggleAutoMeasureBtn();
    });
  }

  // --- 3. Auto Measurement Logic ---
  if (autoMeasureBtn) {
    const measureModalEl = document.getElementById('measureModal');
    const measureModal = new bootstrap.Modal(measureModalEl);
    const measureCanvas = document.getElementById('measureCanvas');
    const ctx = measureCanvas.getContext('2d');
    const measureSlider = document.getElementById('measureSlider');
    const measureFrameText = document.getElementById('measureFrameText');
    const measureResultText = document.getElementById('measureResultText');
    const measureLoading = document.getElementById('measureLoading');
    const localVideo = document.createElement('video');
    localVideo.muted = true; localVideo.playsInline = true;

    let measureState = { points: [], bgImage: new Image(), currentFrame: 0, totalFrames: 0, imgScale: 1, isLocal: false };

    autoMeasureBtn.addEventListener('click', () => {
      if (!currentAnalysis.record_id && (!fileInput.files || fileInput.files.length === 0)) {
        alert('請先選擇影片檔案。'); return;
      }
      measureModal.show();
      if (currentAnalysis.record_id) { measureState.isLocal = false; loadMeasureFrame(0); }
      else { measureState.isLocal = true; setupLocalVideo(); }
    });

    function setupLocalVideo() {
      measureLoading.classList.remove('d-none');
      const file = fileInput.files[0];
      localVideo.src = URL.createObjectURL(file);
      localVideo.onloadedmetadata = () => {
        measureState.totalFrames = Math.floor(localVideo.duration * 30); 
        measureSlider.max = measureState.totalFrames - 1;
        measureSlider.value = 0;
        loadLocalFrame(0);
      };
    }

    async function loadLocalFrame(frameNo) {
      measureLoading.classList.remove('d-none');
      localVideo.currentTime = frameNo / 30;
      localVideo.onseeked = () => {
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = localVideo.videoWidth; tempCanvas.height = localVideo.videoHeight;
        tempCanvas.getContext('2d').drawImage(localVideo, 0, 0);
        measureState.bgImage.onload = () => {
          measureState.currentFrame = frameNo;
          measureFrameText.textContent = `Frame: ${frameNo} / ${measureState.totalFrames - 1}`;
          renderMeasureCanvas();
          measureLoading.classList.add('d-none');
        };
        measureState.bgImage.src = tempCanvas.toDataURL('image/jpeg');
      };
    }

    async function loadMeasureFrame(frameNo) {
      if (measureState.isLocal) return loadLocalFrame(frameNo);
      measureLoading.classList.remove('d-none');
      try {
        const res = await fetch(`/api/get_frame?record_id=${currentAnalysis.record_id}&frame_no=${frameNo}`);
        const data = await res.json();
        if (data.success) {
          measureState.bgImage.onload = () => {
            measureState.totalFrames = data.total_frames;
            measureState.currentFrame = data.current_frame;
            measureSlider.max = data.total_frames - 1;
            measureSlider.value = data.current_frame;
            measureFrameText.textContent = `Frame: ${data.current_frame} / ${data.total_frames - 1}`;
            renderMeasureCanvas();
            measureLoading.classList.add('d-none');
          };
          measureState.bgImage.src = data.frame_data;
        }
      } catch (err) { measureLoading.classList.add('d-none'); }
    }

    function renderMeasureCanvas() {
      const img = measureState.bgImage;
      const scale = Math.min(measureCanvas.parentElement.offsetWidth / img.width, 600 / img.height);
      measureState.imgScale = scale;
      measureCanvas.width = img.width * scale; measureCanvas.height = img.height * scale;
      ctx.drawImage(img, 0, 0, measureCanvas.width, measureCanvas.height);
      ctx.strokeStyle = ctx.fillStyle = '#00ff00'; ctx.lineWidth = 2; ctx.font = '14px Monospace';
      measureState.points.forEach((p, i) => {
        ctx.beginPath(); ctx.arc(p.x * scale, p.y * scale, 5, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(`P${i+1}`, p.x * scale + 10, p.y * scale - 10);
      });
      if (measureState.points.length === 2) {
        const dist = Math.sqrt(Math.pow(measureState.points[1].x - measureState.points[0].x, 2) + Math.pow(measureState.points[1].y - measureState.points[0].y, 2));
        ctx.beginPath(); ctx.moveTo(measureState.points[0].x * scale, measureState.points[0].y * scale);
        ctx.lineTo(measureState.points[1].x * scale, measureState.points[1].y * scale); ctx.stroke();
        measureResultText.textContent = dist.toFixed(2);
      } else measureResultText.textContent = '0.00';
    }

    measureCanvas.addEventListener('mousedown', (e) => {
      const rect = measureCanvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / measureState.imgScale, y = (e.clientY - rect.top) / measureState.imgScale;
      if (measureState.points.length >= 2) measureState.points = [];
      measureState.points.push({ x, y }); renderMeasureCanvas();
    });

    measureCanvas.oncontextmenu = (e) => { e.preventDefault(); measureState.points.pop(); renderMeasureCanvas(); };
    measureSlider.oninput = () => { measureFrameText.textContent = `Frame: ${measureSlider.value} / ${measureState.totalFrames - 1}`; };
    measureSlider.onchange = () => { loadMeasureFrame(measureSlider.value); };
    document.getElementById('measurePrevFrame').onclick = () => { if (measureState.currentFrame > 0) loadMeasureFrame(measureState.currentFrame - 1); };
    document.getElementById('measureNextFrame').onclick = () => { if (measureState.currentFrame < measureState.totalFrames - 1) loadMeasureFrame(measureState.currentFrame + 1); };
    document.getElementById('measureClearBtn').onclick = () => { measureState.points = []; renderMeasureCanvas(); };
    document.getElementById('measureConfirmBtn').onclick = () => {
      if (measureState.points.length === 2) {
        scalePxInput.value = Math.round(parseFloat(measureResultText.textContent));
        measureModal.hide(); alert('測量完成！');
      } else alert('請點擊兩點。');
    };
  }

  // --- 4. Upload & Analyze Logic ---
  if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (fileInput.files.length === 0) { alert('請選擇檔案'); return; }
      const formData = new FormData(uploadForm);
      const jobId = 'job_' + Date.now(); formData.append('job_id', jobId);
      const startBtn = document.getElementById('startBtn');
      try {
        startBtn.disabled = true;
        document.getElementById('progressContainer').classList.remove('d-none');
        const poll = setInterval(async () => {
          const res = await fetch(`/api/progress/${jobId}`);
          if (res.ok) {
            const d = await res.json();
            document.getElementById('progressBar').style.width = d.progress + '%';
            document.getElementById('progressStatus').textContent = d.status;
            document.getElementById('progressPercent').textContent = Math.round(d.progress) + '%';
            if (d.progress >= 100) clearInterval(poll);
          }
        }, 1000);
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const result = await res.json();
        if (res.ok) {
          currentAnalysis.record_id = result.record_id;
          currentAnalysis.person_records = result.person_records;
          currentAnalysis.fps = result.fps || 30;
          toggleAutoMeasureBtn();
          document.getElementById('detectionResults').classList.remove('d-none');
          document.getElementById('uploadBtnContainer').classList.add('d-none');
          document.getElementById('intervalList').innerHTML = result.person_records.map((r, i) => `<div>#${i+1}: ${((r[1]-r[0])/currentAnalysis.fps).toFixed(2)}s</div>`).join('');
          document.getElementById('detectionResults').scrollIntoView({ behavior: 'smooth' });
        } else alert(result.error);
      } catch (err) { alert('發生錯誤'); } finally { startBtn.disabled = false; }
    });

    document.getElementById('confirmAnalyzeBtn').onclick = async () => {
      const jobId = 'job_analyze_' + Date.now();
      const confirmBtn = document.getElementById('confirmAnalyzeBtn');
      confirmBtn.disabled = true;
      const poll = setInterval(async () => {
        const res = await fetch(`/api/progress/${jobId}`);
        if (res.ok) {
          const d = await res.json();
          document.getElementById('progressBar').style.width = d.progress + '%';
          document.getElementById('progressPercent').textContent = Math.round(d.progress) + '%';
          document.getElementById('progressStatus').textContent = d.status;
          if (d.progress >= 100) clearInterval(poll);
        }
      }, 1000);
      try {
        const res = await fetch('/api/analyze', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            record_id: currentAnalysis.record_id, job_id: jobId,
            modules: Array.from(document.querySelectorAll('input[name="m"]:checked')).map(cb => cb.value),
            person_records: currentAnalysis.person_records,
            scale_info: { reference: scaleRefInput.value, pixels: scalePxInput.value },
            athlete: document.getElementById('athlete').value,
            session: document.getElementById('session').value,
            note: document.getElementById('note').value
          })
        });
        const result = await res.json();
        if (res.ok) {
          currentAnalysis.peak_data = result.peak_data;
          const videoFrame = document.querySelector('.video-frame');
          if (result.video_url) {
            videoFrame.innerHTML = `<video id="previewVideo" width="100%" height="auto" controls autoplay><source src="${result.video_url}?t=${Date.now()}" type="video/mp4"></video>`;
            document.getElementById('previewSpeedContainer').classList.remove('d-none');
            videoFrame.style.background = 'transparent';
          }
          populatePeakTable(result.peak_data);
          document.getElementById('imuModalBtn').classList.remove('d-none');
          document.getElementById('result').scrollIntoView({ behavior: 'smooth' });
          document.getElementById('detectionResults').classList.add('d-none');
          document.getElementById('uploadBtnContainer').classList.remove('d-none');
        } else alert(result.error);
      } catch (err) { alert('發生錯誤'); } finally { confirmBtn.disabled = false; }
    };
  }

  // --- 5. Peak Table & Regeneration ---
  window.clearFoot = (btn, side) => {
    const row = btn.closest('tr');
    row.querySelector(`.peak-frame-${side}`).textContent = '';
    row.querySelector(`.peak-x-${side}`).textContent = '';
    row.querySelector(`.peak-y-${side}`).textContent = '';
    
    const fR = row.querySelector('.peak-frame-r').textContent.trim();
    const fL = row.querySelector('.peak-frame-l').textContent.trim();
    if (!fR && !fL) {
      row.remove();
    }
    window.sortAndReindexTable();
  };

  function populatePeakTable(peakData) {
    const csvBody = document.getElementById('csvBody');
    if (!csvBody) return;
    if (!peakData || peakData.length === 0) { 
      csvBody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted">無步頻數據</td></tr>'; 
      return; 
    }
    csvBody.innerHTML = peakData.map(row => createRowHTML(row.Frame_Right, row.X_Right, row.Y_Right, row.Frame_Left, row.X_Left, row.Y_Left)).join('');
    window.sortAndReindexTable();
  }

  function createRowHTML(fR, xR, yR, fL, xL, yL) {
    const fmt = (v) => v !== null && v !== undefined && v !== '' ? Math.round(v) : '';
    return `<tr class="peak-row">
      <td class="text-muted row-idx text-center bg-light"></td>
      <td contenteditable="true" class="mono peak-frame-r text-center">${fmt(fR)}</td>
      <td contenteditable="true" class="mono peak-x-r text-center">${fmt(xR)}</td>
      <td contenteditable="true" class="mono peak-y-r text-center">${fmt(yR)}</td>
      <td contenteditable="true" class="mono peak-frame-l text-center">${fmt(fL)}</td>
      <td contenteditable="true" class="mono peak-x-l text-center">${fmt(xL)}</td>
      <td contenteditable="true" class="mono peak-y-l text-center">${fmt(yL)}</td>
      <td class="text-center">
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-danger py-0 px-2" onclick="window.clearFoot(this, 'r')" title="刪除右腳數據">R</button>
          <button class="btn btn-outline-primary py-0 px-2" onclick="window.clearFoot(this, 'l')" title="刪除左腳數據">L</button>
        </div>
      </td>
    </tr>`;
  }

  window.sortAndReindexTable = () => {
    const csvBody = document.getElementById('csvBody');
    if (!csvBody) return;
    const rows = Array.from(csvBody.querySelectorAll('.peak-row'));
    rows.sort((a, b) => {
      const fRa = parseInt(a.querySelector('.peak-frame-r').textContent) || Infinity;
      const fLa = parseInt(a.querySelector('.peak-frame-l').textContent) || Infinity;
      const fRb = parseInt(b.querySelector('.peak-frame-r').textContent) || Infinity;
      const fLb = parseInt(b.querySelector('.peak-frame-l').textContent) || Infinity;
      return Math.min(fRa, fLa) - Math.min(fRb, fLb);
    });
    csvBody.innerHTML = ''; 
    rows.forEach((row, i) => { 
      row.querySelector('.row-idx').textContent = i + 1; 
      csvBody.appendChild(row); 
    });
  };

  window.addNewPeak = () => {
    const csvBody = document.getElementById('csvBody');
    const t = document.createElement('tbody'); t.innerHTML = createRowHTML('', '', '', '', '', '');
    csvBody.appendChild(t.firstElementChild); window.sortAndReindexTable();
  };

  document.getElementById('regenBtn').onclick = async () => {
    if (!currentAnalysis.record_id) return;
    const rows = document.querySelectorAll('.peak-row');
    const newPeakData = Array.from(rows).map(row => ({
      Frame_Right: parseInt(row.querySelector('.peak-frame-r').textContent) || null,
      X_Right: parseFloat(row.querySelector('.peak-x-r').textContent) || null,
      Y_Right: parseFloat(row.querySelector('.peak-y-r').textContent) || null,
      Frame_Left: parseInt(row.querySelector('.peak-frame-l').textContent) || null,
      X_Left: parseFloat(row.querySelector('.peak-x-l').textContent) || null,
      Y_Left: parseFloat(row.querySelector('.peak-y-l').textContent) || null
    }));
    try {
      const res = await fetch('/regenerate_gait', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: currentAnalysis.record_id, peak_data: newPeakData, scale_info: { reference: scaleRefInput.value, pixels: scalePxInput.value }, person_records: currentAnalysis.person_records })
      });
      const result = await res.json();
      if (res.ok) {
        document.querySelector('.video-frame').innerHTML = `<video id="previewVideo" width="100%" height="auto" controls autoplay><source src="${result.video_url}&t=${Date.now()}" type="video/mp4"></video>`;
        alert('重新生成完成！');
      } else alert(result.error);
    } catch (err) { alert('發生錯誤'); }
  };

  document.getElementById('saveProjectBtn').onclick = () => {
    if (!currentAnalysis.record_id) return;
    const athleteSelect = document.getElementById('athlete');
    fetch('/api/line_notify', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record_id: currentAnalysis.record_id, athlete_name: athleteSelect.options[athleteSelect.selectedIndex].text, session_name: document.getElementById('session').value, modules: Array.from(document.querySelectorAll('input[name="m"]:checked')).map(cb => cb.value) })
    }).then(() => alert('專案已保存並發送通知！'));
  };

  document.getElementById('previewSpeed').onchange = () => {
    const v = document.getElementById('previewVideo'); if (v) v.playbackRate = parseFloat(document.getElementById('previewSpeed').value);
  };

  async function loadImuChart() {
    if (!currentAnalysis.record_id) return;
    const type = document.querySelector('input[name="imuType"]:checked').value;
    const container = document.getElementById('imuPlotContainer'), loading = document.getElementById('imuPlotLoading'), noData = document.getElementById('imuNoData');
    container.classList.add('d-none'); noData.classList.add('d-none'); loading.classList.remove('d-none');
    try {
      const res = await fetch(`/api/imu_plot/${currentAnalysis.record_id}?type=${type}&t=${Date.now()}`);
      const data = await res.json();
      if (data.plot_url) { document.getElementById('imuModalPlotImg').src = data.plot_url; container.classList.remove('d-none'); }
      else noData.classList.remove('d-none');
    } catch (err) { noData.classList.remove('d-none'); } finally { loading.classList.add('d-none'); }
  }

  const imuBtn = document.getElementById('imuModalBtn');
  if (imuBtn) {
    const bsImu = new bootstrap.Modal(document.getElementById('imuModal'));
    imuBtn.onclick = () => { bsImu.show(); loadImuChart(); };
    document.querySelectorAll('input[name="imuType"]').forEach(r => r.onchange = loadImuChart);
  }
});
