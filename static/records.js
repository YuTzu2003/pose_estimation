document.addEventListener('DOMContentLoaded', () => {
    const playerSection = document.getElementById('playerSection');
    const recordsSection = document.getElementById('recordsSection');
    const detailSection = document.getElementById('detailSection');
    const playerList = document.getElementById('playerList');
    const recordsList = document.getElementById('recordsList');
    const emptyHint = document.getElementById('emptyHint');
    
    const backToPlayers = document.getElementById('backToPlayers');
    const backToRecords = document.getElementById('backToRecords');
    const breadcrumbNav = document.getElementById('breadcrumbNav');
    
    const statTotal = document.getElementById('statTotal');
    const statAthletes = document.getElementById('statAthletes');
    
    let allPlayers = [];
    let currentPlayer = null;
    let currentRecords = [];
    let poseData = null;
    let chartInstance = null;

    // Load initial data
    fetchPlayers();
    fetchStats();

    function fetchPlayers() {
        fetch('/get_players')
            .then(res => res.json())
            .then(data => {
                allPlayers = data;
                renderPlayers(data);
                statAthletes.textContent = data.length;
            })
            .catch(err => console.error('Error fetching players:', err));
    }

    function fetchStats() {
        fetch('/api/records')
            .then(res => res.json())
            .then(data => {
                statTotal.textContent = data.length;
            })
            .catch(err => console.error('Error fetching stats:', err));
    }

    function renderPlayers(players) {
        updateBreadcrumb('home');
        playerList.innerHTML = '';
        players.forEach(p => {
            const col = document.createElement('div');
            col.className = 'col-md-4 col-lg-3';
            col.innerHTML = `
                <div class="tile player-card h-100 cursor-pointer" data-id="${p.id}" data-name="${p.name}">
                    <div class="tile-num">${p.id}</div>
                    <h5 class="mb-1">${p.name}</h5>
                    <div class="small text-muted">${p.sport || '未指定運動'}</div>
                    <div class="mt-2 mono small">${p.gender || '-'} | ${p.height || '-'}cm | ${p.weight || '-'}kg</div>
                </div>
            `;
            col.querySelector('.player-card').addEventListener('click', () => {
                showRecords(p.id, p.name);
            });
            playerList.appendChild(col);
        });
    }

    function showRecords(playerId, playerName) {
        currentPlayer = { id: playerId, name: playerName };
        updateBreadcrumb('records');
        document.getElementById('currentPlayerName').textContent = playerName;
        
        playerSection.classList.add('d-none');
        recordsSection.classList.remove('d-none');
        detailSection.classList.add('d-none');
        
        fetch(`/api/records?player_id=${playerId}`)
            .then(res => res.json())
            .then(data => {
                currentRecords = data;
                renderRecords(data);
            })
            .catch(err => console.error('Error fetching records:', err));
    }

    function renderRecords(records) {
        recordsList.innerHTML = '';
        if (records.length === 0) {
            emptyHint.classList.remove('d-none');
            return;
        }
        emptyHint.classList.add('d-none');
        
        document.getElementById('resultCount').textContent = `共 ${records.length} 筆紀錄`;

        records.forEach(r => {
            const tile = document.createElement('div');
            tile.className = 'tile d-flex align-items-center gap-4 mb-2';
            tile.style.padding = '1rem 1.25rem';
            tile.innerHTML = `
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <div class="fw-semibold">${r.session}</div>
                    </div>
                    <div class="small text-muted">${r.note || '無備註'}</div>
                </div>
                <div class="mono small text-muted text-end">
                    <div>${r.date}</div>
                </div>
                <div class="ms-3 d-flex gap-2">
                    <button class="btn btn-sm btn-outline-dark view-detail" data-id="${r.id}">查看詳情</button>
                    <button class="btn btn-sm btn-outline-danger delete-record" data-id="${r.id}"><i class="bi bi-trash"></i></button>
                </div>
            `;
            tile.querySelector('.view-detail').addEventListener('click', () => {
                showDetail(r.id);
            });
            tile.querySelector('.delete-record').addEventListener('click', (e) => {
                e.stopPropagation();
                if (confirm('確定要刪除這筆紀錄嗎？此動作無法復原，且會刪除相關影片與資料。')) {
                    deleteRecord(r.id);
                }
            });
            recordsList.appendChild(tile);
        });
    }

    function deleteRecord(recordId) {
        fetch(`/api/record/${recordId}`, { method: 'DELETE' })
            .then(res => res.json())
            .then(data => {
                if (data.message) {
                    alert('紀錄已刪除');
                    // Refresh records list
                    if (currentPlayer) {
                        showRecords(currentPlayer.id, currentPlayer.name);
                    } else {
                        fetchStats();
                    }
                } else {
                    alert('刪除失敗: ' + data.error);
                }
            })
            .catch(err => {
                console.error('Error deleting record:', err);
                alert('刪除時發生錯誤');
            });
    }

    let currentRecordId = null;
    let currentRecordData = null;

    function showDetail(recordId) {
        currentRecordId = recordId;
        fetch(`/api/record/${recordId}`)
            .then(res => res.json())
            .then(record => {
                currentRecordData = record;
                updateBreadcrumb('detail', record);
                document.getElementById('detailSession').textContent = record.session;
                document.getElementById('detailDate').textContent = record.date;
                document.getElementById('detailNote').textContent = record.note || '無備註';

                // Handle Video Visibility
                const videoContainer = document.getElementById('videoContainer');
                const videoDirectLink = document.getElementById('videoDirectLink');
                const poseChartContainer = document.getElementById('poseChartContainer');
                const appendVideoBtn = document.getElementById('appendVideoBtn');

                if (record.original_video || record.result_video) {
                    videoContainer.classList.remove('d-none');
                    poseChartContainer.classList.remove('d-none');
                    appendVideoBtn.classList.add('d-none');

                    const video = document.getElementById('detailVideo');
                    const videoPath = record.result_video || record.original_video;
                    video.innerHTML = '';

                    if (videoDirectLink) {
                        videoDirectLink.innerHTML = `<a href="/media/${videoPath}" target="_blank" class="text-decoration-none" download>點此另開視窗觀看或下載影片</a>`;
                    }                    
                    // Add attributes for mobile/inline playback
                    video.setAttribute('playsinline', '');
                    video.setAttribute('webkit-playsinline', '');
                    
                    const source = document.createElement('source');
                    source.src = `/media/${videoPath}`;
                    source.type = videoPath.toLowerCase().endsWith('.mp4') ? 'video/mp4' : 'video/x-msvideo';
                    video.appendChild(source);
                    video.load();

                    // Apply current playback speed
                    const speedSelector = document.getElementById('videoSpeed');
                    if (speedSelector) {
                        video.playbackRate = parseFloat(speedSelector.value);
                    }
                } else {
                    videoContainer.classList.add('d-none');
                    poseChartContainer.classList.add('d-none');
                    appendVideoBtn.classList.remove('d-none');
                }

                // Handle IMU Visibility
                const imuContainer = document.getElementById('imuContainer');
                const appendImuBtn = document.getElementById('appendImuBtn');
                if (record.imu_csv_path) {
                    imuContainer.classList.remove('d-none');
                    appendImuBtn.classList.add('d-none');
                    document.getElementById('downloadImu').href = `/static/${record.imu_csv_path}`;
                    // Trigger default IMU plot
                    updateImuPlot();
                } else {
                    imuContainer.classList.add('d-none');
                    appendImuBtn.classList.remove('d-none');
                }
                
                if (record.pose_csv) {
                    document.getElementById('downloadPose').href = `/static/${record.pose_csv}`;
                    const parts = ['Right_Ankle', 'Left_Ankle', 'R_Shoulder', 'L_Shoulder', 'R_Hip', 'L_Hip', 'R_Knee', 'L_Knee'];
                    populatePartSelect(parts);
                    updateChart();
                } else {
                    document.getElementById('downloadPose').href = '#';
                }
                
                recordsSection.classList.add('d-none');
                detailSection.classList.remove('d-none');
            })
            .catch(err => console.error('Error fetching record detail:', err));
    }

    // Append Logic
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
        } else {
            formData.append('imu_file', fileInput.files[0]);
        }

        const btn = document.getElementById('submitAppendBtn');
        btn.disabled = true;
        btn.textContent = '處理中...';

        try {
            const res = await fetch('/api/append_data', { method: 'POST', body: formData });
            const data = await res.json();
            if (res.ok) {
                alert('數據已補齊！');
                appendModal.hide();
                showDetail(currentRecordId); // Refresh
            } else {
                alert('失敗: ' + data.error);
            }
        } catch (err) {
            alert('發生錯誤');
        } finally {
            btn.disabled = false;
            btn.textContent = '上傳並處理';
        }
    };

    // Edit logic
    const editModal = new bootstrap.Modal(document.getElementById('editModal'));
    document.getElementById('editRecordBtn').onclick = () => {
        if (!currentRecordData) return;
        document.getElementById('editSession').value = currentRecordData.session;
        document.getElementById('editNote').value = currentRecordData.note || '';
        editModal.show();
    };

    document.getElementById('saveEditBtn').onclick = () => {
        const sessionName = document.getElementById('editSession').value.trim();
        const note = document.getElementById('editNote').value.trim();
        
        if (!sessionName) {
            alert('場次名稱不能為空');
            return;
        }

        fetch(`/api/record/${currentRecordId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_name: sessionName, note: note })
        })
        .then(res => res.json())
        .then(data => {
            if (data.message) {
                editModal.hide();
                alert('更新成功');
                showDetail(currentRecordId); // Refresh detail view
            } else {
                alert('更新失敗: ' + data.error);
            }
        })
        .catch(err => console.error('Error updating record:', err));
    };

    function populatePartSelect(parts) {
        const select = document.getElementById('partSelect');
        select.innerHTML = '';
        parts.forEach(part => {
            const option = document.createElement('option');
            option.value = part;
            option.textContent = part.replace(/_/g, ' ');
            select.appendChild(option);
        });
        select.onchange = updateChart;
    }

    function updateChart() {
        const part = document.getElementById('partSelect').value;
        const img = document.getElementById('posePlot');
        const spinner = document.getElementById('plotSpinner');
        
        if (!currentRecordId || !part) return;

        img.classList.add('d-none');
        spinner.classList.remove('d-none');

        fetch(`/api/plot_image/${currentRecordId}?part=${part}`)
            .then(res => res.json())
            .then(data => {
                if (data.plot_url) {
                    img.src = data.plot_url;
                    img.classList.remove('d-none');
                } else {
                    console.error('Plot error:', data.error);
                }
                spinner.classList.add('d-none');
            })
            .catch(err => {
                console.error('Error fetching plot image:', err);
                spinner.classList.add('d-none');
            });
    }

    function updateImuPlot() {
        const type = document.getElementById('imuPlotType').value;
        const img = document.getElementById('imuPlot');
        const spinner = document.getElementById('imuPlotSpinner');
        
        if (!currentRecordId || !type) return;

        img.style.opacity = '0.3';
        spinner.classList.remove('d-none');

        fetch(`/api/imu_plot/${currentRecordId}?type=${type}`)
            .then(res => res.json())
            .then(data => {
                if (data.plot_url) {
                    img.src = data.plot_url;
                    img.style.opacity = '1';
                } else {
                    console.error('IMU Plot error:', data.error);
                }
                spinner.classList.add('d-none');
            })
            .catch(err => {
                console.error('Error fetching IMU plot:', err);
                spinner.classList.add('d-none');
                img.style.opacity = '1';
            });
    }

    document.getElementById('imuPlotType').onchange = updateImuPlot;

    document.getElementById('deleteImuDataBtn').onclick = () => {
        if (currentRecordId && confirm('確定要刪除此紀錄中的 IMU 數據嗎？此動作無法復原。')) {
            fetch(`/api/record/${currentRecordId}/imu`, { method: 'DELETE' })
                .then(res => res.json())
                .then(data => {
                    if (data.message) {
                        alert('IMU 數據已刪除');
                        showDetail(currentRecordId); // Refresh to show "Append" button
                    } else {
                        alert('刪除失敗: ' + data.error);
                    }
                })
                .catch(err => console.error('Error deleting IMU data:', err));
        }
    };

    function updateBreadcrumb(level, recordData = null) {
        // Reset breadcrumb
        breadcrumbNav.innerHTML = '';
        
        // Home always exists
        const homeLi = document.createElement('li');
        homeLi.className = 'breadcrumb-item';
        const homeA = document.createElement('a');
        homeA.href = '#';
        homeA.className = 'text-decoration-none text-muted';
        homeA.textContent = '選手列表';
        homeA.onclick = (e) => {
            e.preventDefault();
            backToPlayers.onclick();
        };
        homeLi.appendChild(homeA);
        breadcrumbNav.appendChild(homeLi);

        if (level === 'home') {
            homeLi.classList.add('active');
            homeLi.innerHTML = '選手列表';
        }

        if (level === 'records' || level === 'detail') {
            const playerLi = document.createElement('li');
            playerLi.className = 'breadcrumb-item';
            if (level === 'records') {
                playerLi.classList.add('active');
                playerLi.textContent = `選手: ${currentPlayer.name} (ID: ${currentPlayer.id})`;
            } else {
                const playerA = document.createElement('a');
                playerA.href = '#';
                playerA.className = 'text-decoration-none text-muted';
                playerA.textContent = `選手: ${currentPlayer.name} (ID: ${currentPlayer.id})`;
                playerA.onclick = (e) => {
                    e.preventDefault();
                    backToRecords.onclick();
                };
                playerLi.appendChild(playerA);
            }
            breadcrumbNav.appendChild(playerLi);
        }

        if (level === 'detail' && recordData) {
            const recordLi = document.createElement('li');
            recordLi.className = 'breadcrumb-item active';
            recordLi.textContent = `紀錄: ${recordData.session} (資料夾: ${recordData.id})`;
            breadcrumbNav.appendChild(recordLi);
        }
    }

    backToPlayers.onclick = () => {
        updateBreadcrumb('home');
        recordsSection.classList.add('d-none');
        playerSection.classList.remove('d-none');
        emptyHint.classList.add('d-none');
    };

    backToRecords.onclick = () => {
        updateBreadcrumb('records');
        detailSection.classList.add('d-none');
        recordsSection.classList.remove('d-none');
        const video = document.getElementById('detailVideo');
        video.pause();
        video.src = '';
    };

    document.getElementById('deleteCurrentRecord').onclick = () => {
        if (currentRecordId && confirm('確定要刪除這筆紀錄嗎？此動作無法復原。')) {
            fetch(`/api/record/${currentRecordId}`, { method: 'DELETE' })
                .then(res => res.json())
                .then(data => {
                    if (data.message) {
                        alert('紀錄已刪除');
                        backToRecords.onclick(); // Go back to list
                        if (currentPlayer) {
                            showRecords(currentPlayer.id, currentPlayer.name);
                        }
                    } else {
                        alert('刪除失敗: ' + data.error);
                    }
                })
                .catch(err => console.error('Error deleting record:', err));
        }
    };

    // Search functionality
    document.getElementById('searchInput').oninput = (e) => {
        const term = e.target.value.toLowerCase();
        const filtered = currentRecords.filter(r => 
            r.session.toLowerCase().includes(term) || 
            (r.note && r.note.toLowerCase().includes(term))
        );
        renderRecords(filtered);
    };

    // Playback speed control
    const videoSpeed = document.getElementById('videoSpeed');
    const detailVideo = document.getElementById('detailVideo');
    if (videoSpeed && detailVideo) {
        videoSpeed.addEventListener('change', () => {
            detailVideo.playbackRate = parseFloat(videoSpeed.value);
        });
    }
});
