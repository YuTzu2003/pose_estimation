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
                    <div class="fw-semibold">${r.session}</div>
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
                document.getElementById('detailNote').textContent = record.note;
                
                const video = document.getElementById('detailVideo');
                const videoPath = record.result_video || record.original_video;
                video.innerHTML = '';
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
                
                document.getElementById('downloadPose').href = `/static/${record.pose_csv}`;
                
                recordsSection.classList.add('d-none');
                detailSection.classList.remove('d-none');
                
                // Parts based on standard pose output
                const parts = [
                    'Right_Ankle', 'Left_Ankle', 'R_Shoulder', 'L_Shoulder', 
                    'R_Hip', 'L_Hip', 'R_Knee', 'L_Knee'
                ];
                populatePartSelect(parts);
                updateChart();
            })
            .catch(err => console.error('Error fetching record detail:', err));
    }

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
