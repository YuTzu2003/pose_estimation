document.addEventListener('DOMContentLoaded', () => {
  // --- 1. State & Global Variables ---
  let currentSession = {
    session_id: null,
    records: [], // List of { record_id, person_records, fps, filename, orig_video_path, analysis_result }
    activeRecordId: null
  };

  const autoMeasureBtn = document.getElementById('autoMeasureBtn');
  const scalePreset = document.getElementById('scalePreset');
  const scaleRefInput = document.getElementById('scale_reference');
  const scalePxInput = document.getElementById('scale_pixels');
  const presetInfo = document.getElementById('presetInfo');

  const toggleAutoMeasureBtn = () => {
    if (autoMeasureBtn && scalePreset) {
      const hasLocalFile = fileInput && fileInput.files.length > 0;
      const hasRecord = currentSession.records.length > 0;
      if (scalePreset.value === 'custom' && (hasRecord || hasLocalFile)) {
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
        if (fileInput.files.length === 1) {
          fileNameDisplay.textContent = fileInput.files[0].name;
        } else {
          fileNameDisplay.textContent = `已選取 ${fileInput.files.length} 個影片`;
        }
        fileNameDisplay.style.color = 'var(--fg)';
      } else {
        fileNameDisplay.textContent = '未選取檔案';
        fileNameDisplay.style.color = 'var(--muted)';
      }
      toggleAutoMeasureBtn();
    });
  }

  if (imuInput && imuFileNameDisplay) {
    imuInput.addEventListener('change', () => {
      if (imuInput.files.length > 0) {
        imuFileNameDisplay.textContent = imuInput.files[0].name;
        imuFileNameDisplay.style.color = 'var(--fg)';
      } else {
        imuFileNameDisplay.textContent = '未選取檔案';
        imuFileNameDisplay.style.color = 'var(--muted)';
      }
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
      if (currentSession.records.length === 0 && (!fileInput.files || fileInput.files.length === 0)) {
        alert('請先選擇影片檔案。'); return;
      }
      measureModal.show();
      if (currentSession.records.length > 0) { 
        measureState.isLocal = false; 
        loadMeasureFrame(currentSession.activeRecordId || currentSession.records[0].record_id, 0); 
      }
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

    async function loadMeasureFrame(recordId, frameNo) {
      if (measureState.isLocal) return loadLocalFrame(frameNo);
      measureLoading.classList.remove('d-none');
      try {
        const res = await fetch(`/api/get_frame?record_id=${recordId}&frame_no=${frameNo}`);
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
      ctx.strokeStyle = ctx.fillStyle = '#00ff00'; ctx.lineWidth = 1; ctx.font = '12px Monospace';
      measureState.points.forEach((p, i) => {
        ctx.beginPath(); ctx.arc(p.x * scale, p.y * scale, 2, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(`P${i+1}`, p.x * scale + 5, p.y * scale - 5);
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
    measureSlider.onchange = () => { 
        const rid = currentSession.activeRecordId || currentSession.records[0].record_id;
        loadMeasureFrame(rid, measureSlider.value); 
    };
    document.getElementById('measurePrevFrame').onclick = () => { 
        if (measureState.currentFrame > 0) {
            const rid = currentSession.activeRecordId || currentSession.records[0].record_id;
            loadMeasureFrame(rid, measureState.currentFrame - 1); 
        }
    };
    document.getElementById('measureNextFrame').onclick = () => { 
        if (measureState.currentFrame < measureState.totalFrames - 1) {
            const rid = currentSession.activeRecordId || currentSession.records[0].record_id;
            loadMeasureFrame(rid, measureState.currentFrame + 1); 
        }
    };
    document.getElementById('measureClearBtn').onclick = () => { measureState.points = []; renderMeasureCanvas(); };
    document.getElementById('measureConfirmBtn').onclick = () => {
      if (measureState.points.length === 2) {
        scalePxInput.value = Math.round(parseFloat(measureResultText.textContent));
        measureModal.hide(); alert('測量完成！');
      } else alert('請點擊兩點。');
    };
  }

  // --- 4. Point Picker Logic ---
  const openPickerBtn = document.getElementById('openPickerBtn');
  if (openPickerBtn) {
    const pickerModalEl = document.getElementById('pickerModal');
    const pickerModal = new bootstrap.Modal(pickerModalEl);
    const pickerCanvas = document.getElementById('pickerCanvas');
    const ctx = pickerCanvas.getContext('2d');
    const pickerSlider = document.getElementById('pickerSlider');
    const pickerFrameText = document.getElementById('pickerFrameText');
    const pickerResultText = document.getElementById('pickerResultText');
    const pickerLoading = document.getElementById('pickerLoading');
    const localVideo = document.createElement('video');
    localVideo.muted = true; localVideo.playsInline = true;

    let pickerState = { point: null, bgImage: new Image(), currentFrame: 0, totalFrames: 0, imgScale: 1, isLocal: false };

    openPickerBtn.addEventListener('click', () => {
      if (currentSession.records.length === 0 && (!fileInput.files || fileInput.files.length === 0)) {
        alert('請先選擇影片檔案。'); return;
      }
      pickerModal.show();
      if (currentSession.records.length > 0) { 
        pickerState.isLocal = false; 
        loadPickerFrame(currentSession.activeRecordId, 0); 
      }
      else { pickerState.isLocal = true; setupLocalVideo(); }
    });

    function setupLocalVideo() {
      pickerLoading.classList.remove('d-none');
      const file = fileInput.files[0];
      localVideo.src = URL.createObjectURL(file);
      localVideo.onloadedmetadata = () => {
        pickerState.totalFrames = Math.floor(localVideo.duration * 30); 
        pickerSlider.max = pickerState.totalFrames - 1;
        pickerSlider.value = 0;
        loadLocalFrame(0);
      };
    }

    async function loadLocalFrame(frameNo) {
      pickerLoading.classList.remove('d-none');
      localVideo.currentTime = frameNo / 30;
      localVideo.onseeked = () => {
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = localVideo.videoWidth; tempCanvas.height = localVideo.videoHeight;
        tempCanvas.getContext('2d').drawImage(localVideo, 0, 0);
        pickerState.bgImage.onload = () => {
          pickerState.currentFrame = frameNo;
          pickerFrameText.textContent = `Frame: ${frameNo} / ${pickerState.totalFrames - 1}`;
          renderPickerCanvas();
          pickerLoading.classList.add('d-none');
        };
        pickerState.bgImage.src = tempCanvas.toDataURL('image/jpeg');
      };
    }

    async function loadPickerFrame(recordId, frameNo) {
      if (pickerState.isLocal) return loadLocalFrame(frameNo);
      pickerLoading.classList.remove('d-none');
      try {
        const res = await fetch(`/api/get_frame?record_id=${recordId}&frame_no=${frameNo}`);
        const data = await res.json();
        if (data.success) {
          pickerState.bgImage.onload = () => {
            pickerState.totalFrames = data.total_frames;
            pickerState.currentFrame = data.current_frame;
            pickerSlider.max = data.total_frames - 1;
            pickerSlider.value = data.current_frame;
            pickerFrameText.textContent = `Frame: ${data.current_frame} / ${data.total_frames - 1}`;
            renderPickerCanvas();
            pickerLoading.classList.add('d-none');
          };
          pickerState.bgImage.src = data.frame_data;
        }
      } catch (err) { pickerLoading.classList.add('d-none'); }
    }

    function renderPickerCanvas() {
      const img = pickerState.bgImage;
      const scale = Math.min(pickerCanvas.parentElement.offsetWidth / img.width, 600 / img.height);
      pickerState.imgScale = scale;
      pickerCanvas.width = img.width * scale; pickerCanvas.height = img.height * scale;
      ctx.drawImage(img, 0, 0, pickerCanvas.width, pickerCanvas.height);
      
      if (pickerState.point) {
        const p = pickerState.point;
        ctx.strokeStyle = '#ff0000'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(p.x * scale, p.y * scale, 3, 0, Math.PI * 2); ctx.stroke();
        // Crosshair
        ctx.beginPath(); ctx.moveTo(p.x * scale - 10, p.y * scale); ctx.lineTo(p.x * scale + 10, p.y * scale); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(p.x * scale, p.y * scale - 10); ctx.lineTo(p.x * scale, p.y * scale + 10); ctx.stroke();
        pickerResultText.textContent = `X: ${Math.round(p.x)}, Y: ${Math.round(p.y)}`;
      } else {
        pickerResultText.textContent = 'X: 0, Y: 0';
      }
    }

    pickerCanvas.addEventListener('mousedown', (e) => {
      const rect = pickerCanvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / pickerState.imgScale, y = (e.clientY - rect.top) / pickerState.imgScale;
      pickerState.point = { x, y }; renderPickerCanvas();
    });

    pickerSlider.oninput = () => { pickerFrameText.textContent = `Frame: ${pickerSlider.value} / ${pickerState.totalFrames - 1}`; };
    pickerSlider.onchange = () => { loadPickerFrame(currentSession.activeRecordId, pickerSlider.value); };
    document.getElementById('pickerPrevFrame').onclick = () => { 
        if (pickerState.currentFrame > 0) loadPickerFrame(currentSession.activeRecordId, pickerState.currentFrame - 1); 
    };
    document.getElementById('pickerNextFrame').onclick = () => { 
        if (pickerState.currentFrame < pickerState.totalFrames - 1) loadPickerFrame(currentSession.activeRecordId, pickerState.currentFrame + 1); 
    };
    document.getElementById('pickerClearBtn').onclick = () => { pickerState.point = null; renderPickerCanvas(); };

    function fillTableData(side, frame, x, y) {
      const csvBody = document.getElementById('csvBody');
      let rows = csvBody.querySelectorAll('.peak-row');
      let targetRow = rows.length > 0 ? rows[rows.length - 1] : null;

      // Check if last row already has data for this side
      const frameVal = targetRow ? targetRow.querySelector(`.peak-frame-${side}`).textContent.trim() : '';
      
      if (!targetRow || frameVal !== '') {
        window.addNewPeak();
        rows = csvBody.querySelectorAll('.peak-row');
        targetRow = rows[rows.length - 1];
      }

      targetRow.querySelector(`.peak-frame-${side}`).textContent = Math.round(frame);
      targetRow.querySelector(`.peak-x-${side}`).textContent = Math.round(x);
      targetRow.querySelector(`.peak-y-${side}`).textContent = Math.round(y);
      
      window.sortAndReindexTable();
    }

    document.getElementById('recordRightBtn').onclick = () => {
      if (!pickerState.point) return alert('請先在畫面上點擊選取一點');
      fillTableData('r', pickerState.currentFrame, pickerState.point.x, pickerState.point.y);
      pickerState.point = null; renderPickerCanvas();
    };

    document.getElementById('recordLeftBtn').onclick = () => {
      if (!pickerState.point) return alert('請先在畫面上點擊選取一點');
      fillTableData('l', pickerState.currentFrame, pickerState.point.x, pickerState.point.y);
      pickerState.point = null; renderPickerCanvas();
    };
  }

  // --- 5. Upload & Analyze Logic ---
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
          }
        }, 1000);
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const result = await res.json();
        if (res.ok) {
          currentSession.session_id = result.session_id;
          currentSession.records = result.results;
          toggleAutoMeasureBtn();
          document.getElementById('detectionResults').classList.remove('d-none');
          document.getElementById('uploadBtnContainer').classList.add('d-none');
          
          let html = '';
          result.results.forEach((rec, i) => {
            html += `<div class="mb-2"><strong>影片 ${i+1} (${rec.filename}):</strong>`;
            if (rec.person_records.length > 0) {
                html += rec.person_records.map((r, ri) => `<div class="ms-3 small">區間 ${ri+1}: ${((r[1]-r[0])/rec.fps).toFixed(2)}s</div>`).join('');
            } else {
                html += `<div class="ms-3 small text-danger">未偵測到人物</div>`;
            }
            html += `</div>`;
          });
          document.getElementById('intervalList').innerHTML = html;
          document.getElementById('detectionResults').scrollIntoView({ behavior: 'smooth' });
        } else alert(result.error);
        clearInterval(poll);
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
        }
      }, 1000);

      try {
        for (let i = 0; i < currentSession.records.length; i++) {
          const rec = currentSession.records[i];
          document.getElementById('progressStatus').textContent = `正在分析影片 ${i+1}/${currentSession.records.length}...`;

          const res = await fetch('/api/analyze', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              record_id: rec.record_id, job_id: jobId,
              modules: Array.from(document.querySelectorAll('input[name="m"]:checked')).map(cb => cb.value),
              person_records: rec.person_records,
              scale_info: { reference: scaleRefInput.value, pixels: scalePxInput.value },
              athlete: document.getElementById('athlete').value,
              session: document.getElementById('session').value
            })
          });
          const result = await res.json();
          if (!res.ok) { alert(`影片 ${i+1} 分析失敗: ${result.error}`); break; }

          // Store analysis result back into the record object
          currentSession.records[i].analysis_result = result;
        }
        
        // After all analyzed, show results
        renderRecordSelector();
        switchRecord(currentSession.records[0].record_id);
        
        document.getElementById('imuModalBtn').classList.remove('d-none');
        document.getElementById('result').scrollIntoView({ behavior: 'smooth' });
        document.getElementById('detectionResults').classList.add('d-none');
        document.getElementById('uploadBtnContainer').classList.remove('d-none');
        alert('所有影片分析完成！');
      } catch (err) { alert('發生錯誤'); } finally { 
        clearInterval(poll);
        confirmBtn.disabled = false; 
      }
    };
  }

  function renderRecordSelector() {
    const selector = document.getElementById('recordSelector');
    selector.innerHTML = '';
    selector.classList.remove('d-none');
    
    currentSession.records.forEach((rec, i) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm btn-outline-dark text-nowrap';
        btn.id = `btn-rec-${rec.record_id}`;
        btn.innerHTML = `<i class="bi bi-play-circle me-1"></i>影片 ${i+1}`;
        btn.onclick = () => switchRecord(rec.record_id);
        selector.appendChild(btn);
    });
  }

  function switchRecord(recordId) {
    const rec = currentSession.records.find(r => r.record_id === recordId);
    if (!rec || !rec.analysis_result) return;
    
    currentSession.activeRecordId = recordId;
    
    // Update Active Button UI
    document.querySelectorAll('#recordSelector button').forEach(b => b.classList.replace('btn-dark', 'btn-outline-dark'));
    const activeBtn = document.getElementById(`btn-rec-${recordId}`);
    if (activeBtn) activeBtn.classList.replace('btn-outline-dark', 'btn-dark');

    // Update Video
    const videoFrame = document.querySelector('.video-frame');
    const result = rec.analysis_result;
    if (result.video_url) {
      videoFrame.innerHTML = `<video id="previewVideo" width="100%" height="auto" controls autoplay><source src="${result.video_url}?t=${Date.now()}" type="video/mp4"></video>`;
      document.getElementById('previewSpeedContainer').classList.remove('d-none');
      videoFrame.style.background = 'transparent';
      
      // Sync speed
      const v = document.getElementById('previewVideo');
      if (v) v.playbackRate = parseFloat(document.getElementById('previewSpeed').value);
    }

    // Update Peak Table
    populatePeakTable(result.peak_data);
  }

  // --- 6. Peak Table & Regeneration ---
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
      csvBody.innerHTML = '<tr><td colspan="9" class="text-center py-4 text-muted">無步頻數據</td></tr>'; 
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
      <td class="text-center">
        <button class="btn btn-outline-danger py-0 px-2" onclick="window.clearFoot(this, 'r')" title="刪除右腳數據"><i class="bi bi-trash"></i></button>
      </td>
      <td contenteditable="true" class="mono peak-frame-l text-center">${fmt(fL)}</td>
      <td contenteditable="true" class="mono peak-x-l text-center">${fmt(xL)}</td>
      <td contenteditable="true" class="mono peak-y-l text-center">${fmt(yL)}</td>
      <td class="text-center">
        <button class="btn btn-outline-primary py-0 px-2" onclick="window.clearFoot(this, 'l')" title="刪除左腳數據"><i class="bi bi-trash"></i></button>
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
    if (!currentSession.activeRecordId) return;
    const recordId = currentSession.activeRecordId;
    const activeRec = currentSession.records.find(r => r.record_id === recordId);
    
    const rows = document.querySelectorAll('.peak-row');
    const newPeakData = Array.from(rows).map(row => ({
      Frame_Right: parseInt(row.querySelector('.peak-frame-r').textContent) || null,
      X_Right: parseFloat(row.querySelector('.peak-x-r').textContent) || null,
      Y_Right: parseFloat(row.querySelector('.peak-y-r').textContent) || null,
      Frame_Left: parseInt(row.querySelector('.peak-frame-l').textContent) || null,
      X_Left: parseFloat(row.querySelector('.peak-x-l').textContent) || null,
      Y_Left: parseFloat(row.querySelector('.peak-y-l').textContent) || null
    }));
    
    const btn = document.getElementById('regenBtn');
    btn.disabled = true; btn.textContent = '正在重新產生...';

    try {
      const res = await fetch('/regenerate_gait', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            record_id: recordId, 
            peak_data: newPeakData, 
            scale_info: { reference: scaleRefInput.value, pixels: scalePxInput.value }, 
            person_records: activeRec.person_records 
        })
      });
      const result = await res.json();
      if (res.ok) {
        document.querySelector('.video-frame').innerHTML = `<video id="previewVideo" width="100%" height="auto" controls autoplay><source src="${result.video_url}&t=${Date.now()}" type="video/mp4"></video>`;
        // Update local analysis_result cache
        activeRec.analysis_result.video_url = result.video_url.split('?')[0];
        activeRec.analysis_result.peak_data = newPeakData;
        alert('重新生成完成！');
      } else alert(result.error);
    } catch (err) { alert('發生錯誤'); } finally {
        btn.disabled = false; btn.textContent = '重新產生影片';
    }
  };

  document.getElementById('saveProjectBtn').onclick = () => {
    if (!currentSession.activeRecordId) return;
    const recordId = currentSession.activeRecordId;
    const athleteSelect = document.getElementById('athlete');
    fetch('/api/line_notify', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
          record_id: recordId, 
          athlete_name: athleteSelect.options[athleteSelect.selectedIndex].text, 
          session_name: document.getElementById('session').value, 
          modules: Array.from(document.querySelectorAll('input[name="m"]:checked')).map(cb => cb.value) 
      })
    }).then(() => alert('專案已保存並發送通知！'));
  };

  async function loadImuChart() {
    if (!currentSession.activeRecordId) return;
    const recordId = currentSession.activeRecordId;
    const type = document.querySelector('input[name="imuType"]:checked').value;
    const container = document.getElementById('imuPlotContainer'), loading = document.getElementById('imuPlotLoading'), noData = document.getElementById('imuNoData');
    container.classList.add('d-none'); noData.classList.add('d-none'); loading.classList.remove('d-none');
    try {
      const res = await fetch(`/api/imu_plot/${recordId}?type=${type}&t=${Date.now()}`);
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

  document.getElementById('previewSpeed').onchange = () => {
    const v = document.getElementById('previewVideo'); if (v) v.playbackRate = parseFloat(document.getElementById('previewSpeed').value);
  };
});
