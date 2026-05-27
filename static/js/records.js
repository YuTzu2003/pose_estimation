document.addEventListener('DOMContentLoaded', () => {
    const recordIdInput = document.getElementById('hiddenRecordId');
    if (!recordIdInput) 
        return;

    const currentRecordId = recordIdInput.value;
    const currentPlayerId = document.getElementById('hiddenPlayerId').value;
    const currentProjectFolder = document.getElementById('hiddenProjectFolder').value;
    const detailVideo = document.getElementById('detailVideo');
    const videoSpeed = document.getElementById('videoSpeed');
    initDetailView();

    function initDetailView() {
        // Init Charts
        const imuTile = document.getElementById('imuPlotTile');

        if (imuTile && !imuTile.classList.contains('d-none')) {
            updateImuPlot();
        }

        // Init Multiple Pose Plots
        const poseTiles = document.querySelectorAll('.pose-plot-tile');
        poseTiles.forEach(tile => {
            if (!tile.classList.contains('d-none')) {
                const select = tile.querySelector('.part-select');
                if (select) {
                    const parts = ['Right_Ankle', 'Left_Ankle', 'R_Knee', 'L_Knee', 'R_Hip', 'L_Hip', 'R_Shoulder', 'L_Shoulder'];
                    select.innerHTML = '';
                    parts.forEach(p => { 
                        const o = document.createElement('option'); o.value = p; o.textContent = p.replace(/_/g,' '); select.appendChild(o); 
                    });

                    const recId = tile.dataset.recordId;
                    const updateChart = () => {
                        const part = select.value;
                        const img = tile.querySelector('.pose-plot-img');
                        const spinner = tile.querySelector('.plot-spinner');
                        const noData = tile.querySelector('.pose-no-data');
                        if (img) img.classList.add('d-none');
                        if (noData) noData.classList.add('d-none');
                        if (spinner) spinner.classList.remove('d-none');

                        fetch(`/api/plot_image/${recId}?part=${part}`)
                            .then(res => res.json())
                            .then(data => {
                                if (data.plot_url && img) { 
                                    img.src = data.plot_url; 
                                    img.classList.remove('d-none'); 
                                } else if (noData) {
                                    noData.classList.remove('d-none');
                                }
                                if (spinner) spinner.classList.add('d-none');
                            })
                            .catch(e => {
                                if (noData) noData.classList.remove('d-none');
                                if (spinner) spinner.classList.add('d-none');
                            });
                    };

                    select.onchange = updateChart;
                    const refreshBtn = tile.querySelector('.refresh-pose-btn');
                    if (refreshBtn) refreshBtn.onclick = updateChart;

                    updateChart(); // Initial load
                }
            }
        });
        const toggleGaitEditBtn = document.getElementById('toggleGaitEditBtn');
        if (toggleGaitEditBtn && !toggleGaitEditBtn.classList.contains('d-none')) {
            loadPeakData();
        }
    }

    // --- Note Saving ---
    const saveNoteBtn = document.getElementById('saveNoteBtn');
    if (saveNoteBtn) {
        saveNoteBtn.onclick = () => {
            const note = document.getElementById('detailNote').value;
            saveNoteBtn.disabled = true; saveNoteBtn.textContent = '儲存中...';
            fetch(`/api/record/${currentRecordId}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_name: document.getElementById('detailSession').textContent.trim(), note: note })
            }).then(res => res.json()).then(data => {
                if (data.message) alert('筆記已儲存');
                else alert(data.error);
            }).finally(() => {
                saveNoteBtn.disabled = false; saveNoteBtn.textContent = '儲存筆記';
            });
        };
    }

    // --- Pose Plot ---
    function populatePartSelect(parts) {
        const s = document.getElementById('partSelect'); if (!s) return;
        s.innerHTML = '';
        parts.forEach(p => { const o = document.createElement('option'); o.value = p; o.textContent = p.replace(/_/g,' '); s.appendChild(o); });
        s.onchange = updatePosePlot;
    }
    
    function updatePosePlot() {
        const partSelect = document.getElementById('partSelect');
        if (!partSelect) return;
        const part = partSelect.value;
        const img = document.getElementById('posePlot'), spinner = document.getElementById('plotSpinner');
        if (img) img.classList.add('d-none'); 
        if (spinner) spinner.classList.remove('d-none');
        fetch(`/api/plot_image/${currentRecordId}?part=${part}`).then(res => res.json()).then(data => {
            if (data.plot_url && img) { img.src = data.plot_url; img.classList.remove('d-none'); }
            if (spinner) spinner.classList.add('d-none');
        });
    }
    const refreshPoseBtn = document.getElementById('refreshPoseBtn');
    if (refreshPoseBtn) refreshPoseBtn.onclick = updatePosePlot;

    // --- IMU Plot ---
    function updateImuPlot() {
        const typeSelect = document.getElementById('imuPlotType');
        if (!typeSelect) return;
        const type = typeSelect.value;
        const img = document.getElementById('imuPlot'), spinner = document.getElementById('imuPlotSpinner');
        if (img) img.classList.add('d-none'); 
        if (spinner) spinner.classList.remove('d-none');
        fetch(`/api/imu_plot/${currentRecordId}?type=${type}`).then(res => res.json()).then(data => {
            if (data.plot_url && img) { img.src = data.plot_url; img.classList.remove('d-none'); }
            if (spinner) spinner.classList.add('d-none');
        });
    }
    const imuPlotType = document.getElementById('imuPlotType');
    if (imuPlotType) imuPlotType.onchange = updateImuPlot;
    const refreshImuBtn = document.getElementById('refreshImuBtn');
    if (refreshImuBtn) refreshImuBtn.onclick = updateImuPlot;

    const deleteImuDataBtn = document.getElementById('deleteImuDataBtn');
    if (deleteImuDataBtn) {
        deleteImuDataBtn.onclick = () => {
            if(confirm('確定刪除 IMU 數據？')) {
                fetch(`/api/record/${currentRecordId}/imu`, { method: 'DELETE' }).then(() => window.location.reload());
            }
        };
    }
    
    const deleteCurrentRecord = document.getElementById('deleteCurrentRecord');
    if (deleteCurrentRecord) {
        deleteCurrentRecord.onclick = () => {
            if(confirm('確定刪除此影片紀錄？')) {
                fetch(`/api/record/${currentRecordId}`, { method: 'DELETE' }).then(res => res.json()).then(data => {
                    if (data.message) { 
                        alert('紀錄已刪除'); 
                        window.location.href = `/records/${currentPlayerId}`;
                    }
                    else alert(data.error);
                });
            }
        };
    }

    // --- Gait Correction ---
    function loadPeakData() {
        const peaksPath = `/static/${currentProjectFolder}/${currentRecordId}_peaks.csv?t=${Date.now()}`;
        fetch(peaksPath).then(res => res.text()).then(csvText => {
            const lines = csvText.split('\n');
            if (lines.length < 2) return renderPeakTable([]);
            const headers = lines[0].split(',');
            const data = [];
            for(let i=1; i<lines.length; i++) {
                if(!lines[i]) continue;
                const cols = lines[i].split(',');
                let obj = {}; headers.forEach((h,idx) => obj[h.trim()] = cols[idx]);
                data.push(obj);
            }
            renderPeakTable(data);
        }).catch(err => {
            console.error('Error loading peaks:', err);
            renderPeakTable([]);
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
        const body = document.getElementById('csvBody'); if (!body) return;
        body.innerHTML = '';
        if (data.length === 0) {
            body.innerHTML = '<tr><td colspan="9" class="text-center py-2 text-muted">無步頻數據</td></tr>';
            return;
        }
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
        const body = document.getElementById('csvBody');
        if (!body) return;
        if (body.innerHTML.includes('無步頻數據')) body.innerHTML = '';
        const tr = document.createElement('tr'); tr.className = 'peak-row';
        tr.innerHTML = `<td class="text-center text-muted">*</td>
            <td contenteditable="true" class="peak-frame-r text-center"></td><td contenteditable="true" class="peak-x-r text-center"></td><td contenteditable="true" class="peak-y-r text-center"></td>
            <td class="text-center"><button class="btn btn-link btn-sm text-danger p-0" onclick="window.clearFoot(this, 'r')"><i class="bi bi-trash"></i></button></td>
            <td contenteditable="true" class="peak-frame-l text-center"></td><td contenteditable="true" class="peak-x-l text-center"></td><td contenteditable="true" class="peak-y-l text-center"></td>
            <td class="text-center"><button class="btn btn-link btn-sm text-primary p-0" onclick="window.clearFoot(this, 'l')"><i class="bi bi-trash"></i></button></td>`;
        body.appendChild(tr);
    };

    const regenBtn = document.getElementById('regenBtn');
    if (regenBtn) {
        regenBtn.onclick = async () => {
            const rows = document.querySelectorAll('.peak-row');
            const peakData = Array.from(rows).map(r => ({
                Frame_Right: parseInt(r.querySelector('.peak-frame-r').textContent) || null,
                X_Right: parseFloat(r.querySelector('.peak-x-r').textContent) || null,
                Y_Right: parseFloat(r.querySelector('.peak-y-r').textContent) || null,
                Frame_Left: parseInt(r.querySelector('.peak-frame-l').textContent) || null,
                X_Left: parseFloat(r.querySelector('.peak-x-l').textContent) || null,
                Y_Left: parseFloat(r.querySelector('.peak-y-l').textContent) || null
            }));
            regenBtn.disabled = true; regenBtn.textContent = '生成中...';
            try {
                const res = await fetch('/regenerate_gait', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        record_id: currentRecordId, peak_data: peakData,
                        scale_info: { reference: 1, pixels: 100 }, 
                        person_records: [[0, 9999]]
                    })
                });
                if (res.ok) { alert('生成成功！'); window.location.reload(); } else { const d = await res.json(); alert(d.error); }
            } finally { regenBtn.disabled = false; regenBtn.textContent = '重新生成影片'; }
        };
    }

    // --- Point Picker ---
    const pickerModalEl = document.getElementById('pickerModal');
    if (pickerModalEl) {
        const pickerModal = new bootstrap.Modal(pickerModalEl);
        const canvas = document.getElementById('pickerCanvas');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            let currentPickerIdx = 0, lastPoint = null;

            const openPickerBtn = document.getElementById('openPickerBtn');
            if (openPickerBtn) {
                openPickerBtn.onclick = async () => {
                    const loading = document.getElementById('pickerLoading'); if (loading) loading.classList.remove('d-none');
                    pickerModal.show();
                    currentPickerIdx = 0; updatePickerFrame();
                };
            }

            async function updatePickerFrame() {
                const loading = document.getElementById('pickerLoading'); if (loading) loading.classList.remove('d-none');
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
                            if (loading) loading.classList.add('d-none');
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
                const body = document.getElementById('csvBody');
                if (!body) return;
                if (body.innerHTML.includes('無步頻數據')) body.innerHTML = '';
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
                body.appendChild(tr);
                alert(`已記錄${side === 'R' ? '右' : '左'}腳點位於幀 ${currentPickerIdx}`);
            }
        }
    }

    // --- Modals Logic ---
    const appendModalEl = document.getElementById('appendModal');
    if (appendModalEl) {
        const appendModal = new bootstrap.Modal(appendModalEl);
        const appendForm = document.getElementById('appendForm');

        const appendVideoBtn = document.getElementById('appendVideoBtn');
        if (appendVideoBtn) {
            appendVideoBtn.onclick = () => {
                document.getElementById('appendRecordId').value = currentRecordId;
                document.getElementById('appendType').value = 'video';
                document.getElementById('appendModalTitle').textContent = '補傳分析影片';
                document.getElementById('appendFileLabel').textContent = '選擇影片檔案 (MP4/MOV)';
                document.getElementById('appendFileInput').accept = 'video/*';
                document.getElementById('appendScaleGroup').classList.remove('d-none');
                appendModal.show();
            };
        }

        const appendImuBtn = document.getElementById('appendImuBtn');
        if (appendImuBtn) {
            appendImuBtn.onclick = () => {
                document.getElementById('appendRecordId').value = currentRecordId;
                document.getElementById('appendType').value = 'imu';
                document.getElementById('appendModalTitle').textContent = '補傳 IMU 數據';
                document.getElementById('appendFileLabel').textContent = '選擇數據檔案 (CSV/XLSX)';
                document.getElementById('appendFileInput').accept = '.csv, .xls, .xlsx';
                document.getElementById('appendScaleGroup').classList.add('d-none');
                appendModal.show();
            };
        }

        if (appendForm) {
            appendForm.onsubmit = async (e) => {
                e.preventDefault();
                const type = document.getElementById('appendType').value;
                const formData = new FormData();
                formData.append('record_id', currentRecordId);
                const fileInput = document.getElementById('appendFileInput');
                if (type === 'video') {
                    formData.append('video', fileInput.files[0]);
                    formData.append('scale_reference', document.getElementById('appendScaleRef').value);
                    formData.append('scale_pixels', document.getElementById('appendScalePx').value);
                } else { formData.append('imu_file', fileInput.files[0]); }
                const btn = document.getElementById('submitAppendBtn'); btn.disabled = true; btn.textContent = '上傳中...';
                try {
                    const res = await fetch('/api/append_data', { method: 'POST', body: formData });
                    if (res.ok) { alert('補傳成功！'); window.location.reload(); }
                    else { const d = await res.json(); alert('失敗: ' + d.error); }
                } catch (err) { alert('發生錯誤'); } finally { btn.disabled = false; btn.textContent = '上傳並處理'; }
            };
        }
    }

    const editModalEl = document.getElementById('editModal');
    if (editModalEl) {
        const editModal = new bootstrap.Modal(editModalEl);
        const editRecordBtn = document.getElementById('editRecordBtn');
        if (editRecordBtn) {
            editRecordBtn.onclick = () => {
                document.getElementById('editSession').value = document.getElementById('detailSession').textContent.trim();
                editModal.show();
            };
        }
        const saveEditBtn = document.getElementById('saveEditBtn');
        if (saveEditBtn) {
            saveEditBtn.onclick = () => {
                const session = document.getElementById('editSession').value;
                fetch(`/api/record/${currentRecordId}`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_name: session, note: document.getElementById('detailNote').value })
                }).then(() => { window.location.reload(); });
            };
        }
    }

    const reanalyzeModalEl = document.getElementById('reanalyzeModal');
    if (reanalyzeModalEl) {
        const reanalyzeModal = new bootstrap.Modal(reanalyzeModalEl);
        const reanalyzeBtn = document.getElementById('reanalyzeBtn');
        if (reanalyzeBtn) {
            reanalyzeBtn.onclick = () => {
                reanalyzeModal.show();
            };
        }
        const reanalyzeForm = document.getElementById('reanalyzeForm');
        if (reanalyzeForm) {
            reanalyzeForm.onsubmit = async (e) => {
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
                            modules: modules, person_records: [[0, 9999]], 
                            scale_info: { reference: 1, pixels: 100 },
                            athlete: currentPlayerId, session: document.getElementById('detailSession').textContent.trim(), note: document.getElementById('detailNote').value
                        })
                    });
                    if(res.ok) { alert('分析完成！'); window.location.reload(); }
                } finally { btn.disabled = false; btn.textContent = '確認執行'; }
            };
        }
    }

    if (videoSpeed && detailVideo) {
        videoSpeed.onchange = (e) => { detailVideo.playbackRate = parseFloat(e.target.value); };
    }
});
