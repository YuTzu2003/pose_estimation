document.addEventListener('DOMContentLoaded', () => {
    // --- Global State ---
    let allPlayers = [];
    let currentPlayer = null;
    let currentRecords = [];
    function deleteRecord(recordId) {
        fetch(`/api/record/${recordId}`, { method: 'DELETE' }).then(res => res.json()).then(data => {
            if (data.message) { alert('紀錄已刪除'); backToRecords.onclick(); showRecords(currentPlayer.id, currentPlayer.name); }
            else alert(data.error);
        });
    }

    let currentRecordId = null;
    let currentRecordData = null;
    
    // --- Elements ---
    const playerSection = document.getElementById('playerSection');
    const recordsSection = document.getElementById('recordsSection');
    const detailSection = document.getElementById('detailSection');
    const playerList = document.getElementById('playerList');
    const recordsList = document.getElementById('recordsList');
    
    const backToPlayers = document.getElementById('backToPlayers');
    const backToRecords = document.getElementById('backToRecords');
    const breadcrumbNav = document.getElementById('breadcrumbNav');
    
    const statTotal = document.getElementById('statTotal');
    const statAthletes = document.getElementById('statAthletes');

    // --- Init ---
    fetchPlayers();
    fetchStats();

    function fetchPlayers() {
        fetch('/get_players').then(res => res.json()).then(data => {
            allPlayers = data; renderPlayers(data); statAthletes.textContent = data.length;
        });
    }

    function fetchStats() {
        fetch('/api/records').then(res => res.json()).then(data => { statTotal.textContent = data.length; });
    }

    function renderPlayers(players) {
        updateBreadcrumb('home'); playerList.innerHTML = '';
        players.forEach(p => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-lg-3';
            col.innerHTML = `
                <div class="tile player-card h-100 cursor-pointer" data-id="${p.id}">
                    <div class="tile-num">${p.id}</div>
                    <h5 class="mb-1 fw-bold">${p.name}</h5>
                    <div class="x-small text-muted">${p.sport || '未指定運動'}</div>
                    <div class="mt-2 mono x-small">${p.gender || '-'} | ${p.height || '-'}cm | ${p.weight || '-'}kg</div>
                </div>`;
            col.querySelector('.player-card').onclick = () => showRecords(p.id, p.name);
            playerList.appendChild(col);
        });
    }

    function showRecords(playerId, playerName) {
        currentPlayer = { id: playerId, name: playerName };
        updateBreadcrumb('records');
        document.getElementById('currentPlayerName').textContent = playerName;
        playerSection.classList.add('d-none'); recordsSection.classList.remove('d-none'); detailSection.classList.add('d-none');
        fetch(`/api/records?player_id=${playerId}`).then(res => res.json()).then(data => {
            currentRecords = data; renderRecords(data);
        });
    }

    function renderRecords(records) {
        recordsList.innerHTML = '';
        document.getElementById('statTotal').textContent = records.length;
        records.forEach(r => {
            const tile = document.createElement('div');
            tile.className = 'tile d-flex align-items-center gap-4 mb-3 py-3 px-4';
            tile.innerHTML = `
                <div class="flex-grow-1">
                    <div class="fw-bold fs-6">${r.session}</div>
                    <div class="small text-muted mt-1">${r.note || '無備註'}</div>
                </div>
                <div class="mono small text-muted text-end">${r.date}</div>
                <div class="ms-3 d-flex gap-2">
                    <button class="btn btn-sm btn-outline-dark view-detail" data-id="${r.id}">詳情</button>
                    <button class="btn btn-sm btn-outline-danger delete-record" data-id="${r.id}">刪除</button>
                </div>`;
            tile.querySelector('.view-detail').onclick = () => showDetail(r.id);
            tile.querySelector('.delete-record').onclick = () => { if(confirm('確定刪除？')) deleteRecord(r.id); };
            recordsList.appendChild(tile);
        });
    }

    function showDetail(recordId) {
        currentRecordId = recordId;
        fetch(`/api/record/${recordId}`).then(res => res.json()).then(record => {
            currentRecordData = record;
            updateBreadcrumb('detail', record);
            document.getElementById('detailIdDisplay').textContent = `ID: ${record.id}`;
            document.getElementById('detailPlayerName').textContent = record.player_name;
            document.getElementById('detailSession').textContent = record.session;
            document.getElementById('detailDate').textContent = record.date;
            
            // Scale Info instead of frames
            const scaleText = record.scale_reference ? `${record.scale_reference}m (${record.scale_pixels}px)` : '未設定';
            document.getElementById('detailScaleInfo').textContent = scaleText;

            document.getElementById('detailNote').value = record.note || '';
            
            const modulesDiv = document.getElementById('detailModules');
            modulesDiv.innerHTML = (record.modules || []).map(m => `<span class="badge bg-dark x-small fw-normal me-1">${m}</span>`).join('');
            
            // Video
            const video = document.getElementById('detailVideo');
            const videoPath = record.result_video || record.original_video;
            video.innerHTML = '';
            if (videoPath) {
                const source = document.createElement('source');
                source.src = `/media/${videoPath}?t=${Date.now()}`;
                source.type = 'video/mp4';
                video.appendChild(source); video.load();
                document.getElementById('videoDirectLink').innerHTML = `<a href="/media/${videoPath}" class="btn btn-xs btn-outline-dark" download>下載影片</a>`;
            }

            // Append Buttons Visibility
            document.getElementById('appendVideoBtn').classList.toggle('d-none', !!(record.original_video || record.result_video));
            document.getElementById('appendImuBtn').classList.toggle('d-none', !!record.imu_csv_path);

            // Gait Edit Visibility
            const hasGait = record.modules && record.modules.some(m => m.includes('Stride & Speed') || m.includes('gait'));
            document.getElementById('toggleGaitEditBtn').classList.toggle('d-none', !hasGait);
            if (hasGait) loadPeakData(record.id);

            // Charts
            const poseTile = document.getElementById('posePlotTile');
            const imuTile = document.getElementById('imuPlotTile');
            
            if (record.pose_csv) {
                poseTile.classList.remove('d-none');
                document.getElementById('downloadPose').href = `/static/${record.pose_csv}`;
                populatePartSelect(['Right_Ankle', 'Left_Ankle', 'R_Knee', 'L_Knee', 'R_Hip', 'L_Hip', 'R_Shoulder', 'L_Shoulder']);
                updatePosePlot();
            } else {
                poseTile.classList.add('d-none');
            }

            if (record.imu_csv_path) {
                imuTile.classList.remove('d-none');
                document.getElementById('downloadImu').href = `/media/${record.imu_csv_path}`;
                updateImuPlot();
            } else {
                imuTile.classList.add('d-none');
            }

            recordsSection.classList.add('d-none'); detailSection.classList.remove('d-none');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // --- Note Saving ---
    document.getElementById('saveNoteBtn').onclick = () => {
        const note = document.getElementById('detailNote').value;
        const btn = document.getElementById('saveNoteBtn');
        btn.disabled = true; btn.textContent = '儲存中...';
        fetch(`/api/record/${currentRecordId}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_name: currentRecordData.session, note: note })
        }).then(res => res.json()).then(data => {
            if (data.message) { 
                alert('筆記已儲存'); 
                currentRecordData.note = note;
            } else alert(data.error);
        }).finally(() => {
            btn.disabled = false; btn.textContent = '儲存筆記';
        });
    };

    // --- Pose Plot ---
    function populatePartSelect(parts) {
        const s = document.getElementById('partSelect'); s.innerHTML = '';
        parts.forEach(p => { const o = document.createElement('option'); o.value = p; o.textContent = p.replace(/_/g,' '); s.appendChild(o); });
        s.onchange = updatePosePlot;
    }
    function updatePosePlot() {
        const part = document.getElementById('partSelect').value;
        const img = document.getElementById('posePlot'), spinner = document.getElementById('plotSpinner');
        img.classList.add('d-none'); spinner.classList.remove('d-none');
        fetch(`/api/plot_image/${currentRecordId}?part=${part}`).then(res => res.json()).then(data => {
            if (data.plot_url) { img.src = data.plot_url; img.classList.remove('d-none'); }
            spinner.classList.add('d-none');
        });
    }
    document.getElementById('refreshPoseBtn').onclick = updatePosePlot;

    // --- IMU Plot ---
    function updateImuPlot() {
        const type = document.getElementById('imuPlotType').value;
        const img = document.getElementById('imuPlot'), spinner = document.getElementById('imuPlotSpinner');
        img.classList.add('d-none'); spinner.classList.remove('d-none');
        fetch(`/api/imu_plot/${currentRecordId}?type=${type}`).then(res => res.json()).then(data => {
            if (data.plot_url) { img.src = data.plot_url; img.classList.remove('d-none'); }
            spinner.classList.add('d-none');
        });
    }
    document.getElementById('imuPlotType').onchange = updateImuPlot;
    document.getElementById('refreshImuBtn').onclick = updateImuPlot;
    document.getElementById('deleteImuDataBtn').onclick = () => {
        if(confirm('確定刪除 IMU 數據？')) {
            fetch(`/api/record/${currentRecordId}/imu`, { method: 'DELETE' }).then(() => showDetail(currentRecordId));
        }
    };

    // --- Gait Correction ---
    function loadPeakData(recordId) {
        const projectFolder = currentRecordData.project_folder;
        const peaksPath = `/static/${projectFolder}/${currentRecordId}_peaks.csv?t=${Date.now()}`;
        fetch(peaksPath).then(res => res.text()).then(csvText => {
            const lines = csvText.split('\n');
            const headers = lines[0].split(',');
            const data = [];
            for(let i=1; i<lines.length; i++) {
                if(!lines[i]) continue;
                const cols = lines[i].split(',');
                let obj = {}; headers.forEach((h,idx) => obj[h.trim()] = cols[idx]);
                data.push(obj);
            }
            renderPeakTable(data);
        });
    }

    window.clearFoot = (btn, side) => {
        const tr = btn.closest('tr');
        if (side === 'r') {
            tr.querySelector('.peak-frame-r').textContent = '';
            tr.querySelector('.peak-x-r').textContent = '';
            tr.querySelector('.peak-y-r').textContent = '';
        } else {
            tr.querySelector('.peak-frame-l').textContent = '';
            tr.querySelector('.peak-x-l').textContent = '';
            tr.querySelector('.peak-y-l').textContent = '';
        }
        const fr = tr.querySelector('.peak-frame-r').textContent.trim();
        const fl = tr.querySelector('.peak-frame-l').textContent.trim();
        if (!fr && !fl) tr.remove();
    };

    function renderPeakTable(data) {
        const body = document.getElementById('csvBody'); body.innerHTML = '';
        const fmt = (v) => (v !== null && v !== undefined && v !== '') ? parseFloat(v).toFixed(2) : '';
        data.forEach((row, i) => {
            const tr = document.createElement('tr');
            tr.className = 'peak-row';
            tr.innerHTML = `
                <td class="text-center text-muted">${i+1}</td>
                <td contenteditable="true" class="peak-frame-r text-center">${row.Frame_Right || ''}</td>
                <td contenteditable="true" class="peak-x-r text-center">${fmt(row.X_Right)}</td>
                <td contenteditable="true" class="peak-y-r text-center">${fmt(row.Y_Right)}</td>
                <td class="text-center"><button class="btn btn-link btn-sm text-danger p-0" onclick="window.clearFoot(this, 'r')"><i class="bi bi-trash"></i></button></td>
                <td contenteditable="true" class="peak-frame-l text-center">${row.Frame_Left || ''}</td>
                <td contenteditable="true" class="peak-x-l text-center">${fmt(row.X_Left)}</td>
                <td contenteditable="true" class="peak-y-l text-center">${fmt(row.Y_Left)}</td>
                <td class="text-center"><button class="btn btn-link btn-sm text-primary p-0" onclick="window.clearFoot(this, 'l')"><i class="bi bi-trash"></i></button></td>
            `;
            body.appendChild(tr);
        });
    }

    window.addNewPeak = () => {
        const tr = document.createElement('tr'); tr.className = 'peak-row';
        tr.innerHTML = `<td class="text-center text-muted">*</td>
            <td contenteditable="true" class="peak-frame-r text-center"></td><td contenteditable="true" class="peak-x-r text-center"></td><td contenteditable="true" class="peak-y-r text-center"></td>
            <td class="text-center"><button class="btn btn-link btn-sm text-danger p-0" onclick="window.clearFoot(this, 'r')"><i class="bi bi-trash"></i></button></td>
            <td contenteditable="true" class="peak-frame-l text-center"></td><td contenteditable="true" class="peak-x-l text-center"></td><td contenteditable="true" class="peak-y-l text-center"></td>
            <td class="text-center"><button class="btn btn-link btn-sm text-primary p-0" onclick="window.clearFoot(this, 'l')"><i class="bi bi-trash"></i></button></td>`;
        document.getElementById('csvBody').appendChild(tr);
    };

    document.getElementById('regenBtn').onclick = async () => {
        const rows = document.querySelectorAll('.peak-row');
        const peakData = Array.from(rows).map(r => ({
            Frame_Right: parseInt(r.querySelector('.peak-frame-r').textContent) || null,
            X_Right: parseFloat(r.querySelector('.peak-x-r').textContent) || null,
            Y_Right: parseFloat(r.querySelector('.peak-y-r').textContent) || null,
            Frame_Left: parseInt(r.querySelector('.peak-frame-l').textContent) || null,
            X_Left: parseFloat(r.querySelector('.peak-x-l').textContent) || null,
            Y_Left: parseFloat(r.querySelector('.peak-y-l').textContent) || null
        }));
        const btn = document.getElementById('regenBtn'); btn.disabled = true; btn.textContent = '生成中...';
        try {
            const res = await fetch('/regenerate_gait', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    record_id: currentRecordId, peak_data: peakData,
                    scale_info: { reference: currentRecordData.scale_reference, pixels: currentRecordData.scale_pixels },
                    person_records: [[currentRecordData.frame_start, currentRecordData.frame_end]]
                })
            });
            const data = await res.json();
            if (res.ok) { alert('生成成功！'); showDetail(currentRecordId); } else alert(data.error);
        } finally { btn.disabled = false; btn.textContent = '重新生成影片'; }
    };

    // --- Point Picker ---
    const pickerModal = new bootstrap.Modal(document.getElementById('pickerModal'));
    const canvas = document.getElementById('pickerCanvas'), ctx = canvas.getContext('2d');
    let currentPickerIdx = 0, lastPoint = null;

    document.getElementById('openPickerBtn').onclick = async () => {
        const loading = document.getElementById('pickerLoading'); loading.classList.remove('d-none');
        pickerModal.show();
        currentPickerIdx = 0; updatePickerFrame();
    };

    async function updatePickerFrame() {
        const loading = document.getElementById('pickerLoading'); loading.classList.remove('d-none');
        try {
            const res = await fetch(`/api/get_frame?record_id=${currentRecordId}&frame_no=${currentPickerIdx}`);
            const data = await res.json();
            if (data.success) {
                const img = new Image(); img.onload = () => {
                    canvas.width = img.width; canvas.height = img.height;
                    ctx.drawImage(img, 0, 0); drawCrosshair();
                    document.getElementById('pickerFrameText').textContent = `Frame: ${currentPickerIdx} / ${data.total_frames - 1}`;
                    document.getElementById('pickerSlider').max = data.total_frames - 1;
                    document.getElementById('pickerSlider').value = currentPickerIdx;
                    loading.classList.add('d-none');
                };
                img.src = data.frame_data;
            }
        } catch(e) { console.error(e); }
    }

    function drawCrosshair() {
        if (!lastPoint) return;
        ctx.strokeStyle = '#ff0000'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(lastPoint.x - 10, lastPoint.y); ctx.lineTo(lastPoint.x + 10, lastPoint.y); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(lastPoint.x, lastPoint.y - 10); ctx.lineTo(lastPoint.x, lastPoint.y + 10); ctx.stroke();
    }

    canvas.onclick = (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width, scaleY = canvas.height / rect.height;
        lastPoint = { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
        updatePickerFrame();
        document.getElementById('pickerResultText').textContent = `X: ${Math.round(lastPoint.x)}, Y: ${Math.round(lastPoint.y)}`;
    };

    document.getElementById('pickerSlider').oninput = (e) => { currentPickerIdx = parseInt(e.target.value); updatePickerFrame(); };
    document.getElementById('pickerPrevFrame').onclick = () => { if(currentPickerIdx > 0) { currentPickerIdx--; updatePickerFrame(); } };
    document.getElementById('pickerNextFrame').onclick = () => { currentPickerIdx++; updatePickerFrame(); };

    document.getElementById('recordRightBtn').onclick = () => recordPoint('R');
    document.getElementById('recordLeftBtn').onclick = () => recordPoint('L');

    function recordPoint(side) {
        if (!lastPoint) { alert('請先在畫面上點選位置'); return; }
        const tr = document.createElement('tr'); tr.className = 'peak-row';
        const valX = parseFloat(lastPoint.x).toFixed(2);
        const valY = parseFloat(lastPoint.y).toFixed(2);
        if (side === 'R') {
            tr.innerHTML = `<td class="text-center text-muted">+R</td>
                <td contenteditable="true" class="peak-frame-r text-center">${currentPickerIdx}</td>
                <td contenteditable="true" class="peak-x-r text-center">${valX}</td>
                <td contenteditable="true" class="peak-y-r text-center">${valY}</td>
                <td class="text-center"><button class="btn btn-link btn-sm text-danger p-0" onclick="window.clearFoot(this, 'r')"><i class="bi bi-trash"></i></button></td>
                <td contenteditable="true" class="peak-frame-l text-center"></td><td contenteditable="true" class="peak-x-l text-center"></td><td contenteditable="true" class="peak-y-l text-center"></td>
                <td class="text-center"><button class="btn btn-link btn-sm text-primary p-0" onclick="window.clearFoot(this, 'l')"><i class="bi bi-trash"></i></button></td>`;
        } else {
            tr.innerHTML = `<td class="text-center text-muted">+L</td>
                <td contenteditable="true" class="peak-frame-r text-center"></td><td contenteditable="true" class="peak-x-r text-center"></td><td contenteditable="true" class="peak-y-r text-center"></td>
                <td class="text-center"><button class="btn btn-link btn-sm text-danger p-0" onclick="window.clearFoot(this, 'r')"><i class="bi bi-trash"></i></button></td>
                <td contenteditable="true" class="peak-frame-l text-center">${currentPickerIdx}</td>
                <td contenteditable="true" class="peak-x-l text-center">${valX}</td>
                <td contenteditable="true" class="peak-y-l text-center">${valY}</td>
                <td class="text-center"><button class="btn btn-link btn-sm text-primary p-0" onclick="window.clearFoot(this, 'l')"><i class="bi bi-trash"></i></button></td>`;
        }
        document.getElementById('csvBody').appendChild(tr);
        alert(`已記錄${side === 'R' ? '右' : '左'}腳點位於幀 ${currentPickerIdx}`);
    }

    // --- Others ---
    const appendModal = new bootstrap.Modal(document.getElementById('appendModal'));
    const appendForm = document.getElementById('appendForm');

    document.getElementById('appendVideoBtn').onclick = () => {
        document.getElementById('appendRecordId').value = currentRecordId;
        document.getElementById('appendType').value = 'video';
        document.getElementById('appendModalTitle').textContent = '補傳分析影片';
        document.getElementById('appendFileLabel').textContent = '選擇影片檔案 (MP4/MOV)';
        document.getElementById('appendFileInput').accept = 'video/*';
        document.getElementById('appendScaleGroup').classList.remove('d-none');
        appendModal.show();
    };

    document.getElementById('appendImuBtn').onclick = () => {
        document.getElementById('appendRecordId').value = currentRecordId;
        document.getElementById('appendType').value = 'imu';
        document.getElementById('appendModalTitle').textContent = '補傳 IMU 數據';
        document.getElementById('appendFileLabel').textContent = '選擇數據檔案 (CSV/XLSX)';
        document.getElementById('appendFileInput').accept = '.csv, .xls, .xlsx';
        document.getElementById('appendScaleGroup').classList.add('d-none');
        appendModal.show();
    };

    appendForm.onsubmit = async (e) => {
        e.preventDefault();
        const type = document.getElementById('appendType').value;
        const formData = new FormData();
        formData.append('record_id', document.getElementById('appendRecordId').value);
        const fileInput = document.getElementById('appendFileInput');
        if (type === 'video') {
            formData.append('video', fileInput.files[0]);
            formData.append('scale_reference', document.getElementById('appendScaleRef').value);
            formData.append('scale_pixels', document.getElementById('appendScalePx').value);
        } else { formData.append('imu_file', fileInput.files[0]); }
        const btn = document.getElementById('submitAppendBtn'); btn.disabled = true; btn.textContent = '上傳中...';
        try {
            const res = await fetch('/api/append_data', { method: 'POST', body: formData });
            if (res.ok) { alert('補傳成功！'); appendModal.hide(); showDetail(currentRecordId); }
            else { const d = await res.json(); alert('失敗: ' + d.error); }
        } catch (err) { alert('發生錯誤'); } finally { btn.disabled = false; btn.textContent = '上傳並處理'; }
    };

    const editModal = new bootstrap.Modal(document.getElementById('editModal'));
    document.getElementById('editRecordBtn').onclick = () => {
        document.getElementById('editSession').value = currentRecordData.session;
        editModal.show();
    };
    document.getElementById('saveEditBtn').onclick = () => {
        const session = document.getElementById('editSession').value;
        fetch(`/api/record/${currentRecordId}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_name: session, note: currentRecordData.note })
        }).then(() => { editModal.hide(); showDetail(currentRecordId); });
    };

    const reanalyzeModal = new bootstrap.Modal(document.getElementById('reanalyzeModal'));
    document.getElementById('reanalyzeBtn').onclick = () => {
        document.getElementById('re_scale_ref').value = currentRecordData.scale_reference || 1;
        document.getElementById('re_scale_px').value = currentRecordData.scale_pixels || 100;
        reanalyzeModal.show();
    };
    document.getElementById('reanalyzeForm').onsubmit = async (e) => {
        e.preventDefault();
        const btn = document.getElementById('submitReanalyzeBtn'); btn.disabled = true; btn.textContent = '分析中...';
        const modules = ['angle'];
        if(document.getElementById('re_module_track').checked) modules.push('track');
        if(document.getElementById('re_module_gait').checked) modules.push('gait');
        try {
            const res = await fetch('/api/analyze', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    record_id: currentRecordId, job_id: `re_${Date.now()}`,
                    modules: modules, person_records: [[currentRecordData.frame_start, currentRecordData.frame_end]],
                    scale_info: { reference: document.getElementById('re_scale_ref').value, pixels: document.getElementById('re_scale_px').value },
                    athlete: currentRecordData.player_id, session: currentRecordData.session, note: currentRecordData.note
                })
            });
            if(res.ok) { alert('分析完成！'); reanalyzeModal.hide(); showDetail(currentRecordId); }
        } finally { btn.disabled = false; btn.textContent = '確認執行'; }
    };

    backToPlayers.onclick = () => { playerSection.classList.remove('d-none'); recordsSection.classList.add('d-none'); updateBreadcrumb('home'); };
    backToRecords.onclick = () => { recordsSection.classList.remove('d-none'); detailSection.classList.add('d-none'); document.getElementById('detailVideo').pause(); updateBreadcrumb('records'); };

    function updateBreadcrumb(level, record = null) {
        breadcrumbNav.innerHTML = `<li class="breadcrumb-item"><a href="#" id="pathHome">選手列表</a></li>`;
        document.getElementById('pathHome').onclick = (e) => { e.preventDefault(); backToPlayers.onclick(); };
        if (level === 'records' || level === 'detail') {
            const li = document.createElement('li'); li.className = 'breadcrumb-item';
            li.innerHTML = `<a href="#">${currentPlayer.name}</a>`;
            li.onclick = (e) => { e.preventDefault(); backToRecords.onclick(); };
            breadcrumbNav.appendChild(li);
        }
        if (level === 'detail' && record) {
            const li = document.createElement('li'); li.className = 'breadcrumb-item active'; li.textContent = record.session;
            breadcrumbNav.appendChild(li);
        }
    }
    document.getElementById('videoSpeed').onchange = (e) => { document.getElementById('detailVideo').playbackRate = parseFloat(e.target.value); };
});
