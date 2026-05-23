document.addEventListener('DOMContentLoaded', () => {
    const athleteA = document.getElementById('athleteA');
    const athleteB = document.getElementById('athleteB');
    const recordA = document.getElementById('recordA');
    const recordB = document.getElementById('recordB');
    const compareType = document.getElementById('compareType');
    const jointPickerCol = document.getElementById('jointPickerCol');
    const imuPickerCol = document.getElementById('imuPickerCol');
    const runCompare = document.getElementById('runCompare');
    const cmpResult = document.getElementById('cmpResult');
    
    // UI Logic: Toggle picker columns based on compare type
    compareType.addEventListener('change', () => {
        const val = compareType.value;
        jointPickerCol.style.display = (val === 'skeleton' || val === 'merged') ? 'block' : 'none';
        imuPickerCol.style.display = (val === 'imu' || val === 'merged') ? 'block' : 'none';
    });

    // Fetch records when athlete is selected
    async function fetchRecords(athleteId, targetSelect) {
        if (!athleteId) {
            targetSelect.disabled = true;
            targetSelect.innerHTML = '<option value="">選擇紀錄...</option>';
            return;
        }
        try {
            const res = await fetch(`/api/player_records/${athleteId}`);
            const records = await res.json();
            let html = '<option value="">選擇紀錄...</option>';
            records.forEach(r => {
                html += `<option value="${r.Record_id}" data-video="${r.Result_Video_Path || r.Original_Video_Path}" data-session="${r.Session_name}">${r.Session_name} (${r.Created_at})</option>`;
            });
            targetSelect.innerHTML = html;
            targetSelect.disabled = false;
        } catch (err) {
            console.error("Fetch records error:", err);
        }
    }

    athleteA.addEventListener('change', () => fetchRecords(athleteA.value, recordA));
    athleteB.addEventListener('change', () => fetchRecords(athleteB.value, recordB));

    // Handle video preview
    function updateVideoPreview(selectEl, containerId) {
        const container = document.getElementById(containerId);
        const option = selectEl.options[selectEl.selectedIndex];
        const videoPath = option.dataset.video;

        if (videoPath) {
            container.innerHTML = `
                <video src="/static/${videoPath}" width="100%" height="100%" controls style="object-fit: contain;"></video>
            `;
        } else {
            container.innerHTML = `<span class="text-white-50 small mono">VIDEO ${containerId.slice(-1)}</span>`;
        }
    }

    recordA.addEventListener('change', () => updateVideoPreview(recordA, 'videoContainerA'));
    recordB.addEventListener('change', () => updateVideoPreview(recordB, 'videoContainerB'));

    runCompare.addEventListener('click', async () => {
        const idA = recordA.value;
        const idB = recordB.value;

        if (!idA || !idB) {
            alert("請先選擇兩組紀錄進行比對。");
            return;
        }

        runCompare.disabled = true;
        runCompare.textContent = "比對中...";

        try {
            const type = compareType.value;
            const joint = document.getElementById('jointSelect').value;
            const imuMetric = document.getElementById('imuMetricSelect').value;

            // Fetch data for both records
            const [dataA, dataB] = await Promise.all([
                fetchRecordData(idA),
                fetchRecordData(idB)
            ]);

            cmpResult.hidden = false;
            cmpResult.scrollIntoView({ behavior: 'smooth' });

            renderComparisonChart(dataA, dataB, type, joint, imuMetric);
            renderComparisonTable(dataA, dataB, type, joint, imuMetric);

        } catch (err) {
            console.error("Compare error:", err);
            alert("獲取比對數據時發生錯誤。");
        } finally {
            runCompare.disabled = false;
            runCompare.textContent = "執行比對 / RUN COMPARE";
        }
    });

    async function fetchRecordData(recordId) {
        const res = await fetch(`/api/record_detail/${recordId}`);
        if (!res.ok) throw new Error("Failed to fetch record");
        return await res.json();
    }

    function renderComparisonChart(dataA, dataB, type, joint, imuMetric) {
        const ctx = document.getElementById('cmpChart');
        if (window.cmpChartInstance) window.cmpChartInstance.destroy();

        let datasets = [];
        let labels = [];

        const nameA = `${dataA.record.Player_id} - ${dataA.record.Session_name}`;
        const nameB = `${dataB.record.Player_id} - ${dataB.record.Session_name}`;

        if (type === 'skeleton' || type === 'merged') {
            const seriesA = dataA.pose_data.map(d => d[joint] || 0);
            const seriesB = dataB.pose_data.map(d => d[joint] || 0);
            const maxLen = Math.max(seriesA.length, seriesB.length);
            labels = Array.from({ length: maxLen }, (_, i) => i);

            datasets.push({
                label: `${nameA} (${joint})`,
                data: seriesA,
                borderColor: '#171717',
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: 'y'
            });
            datasets.push({
                label: `${nameB} (${joint})`,
                data: seriesB,
                borderColor: '#a3a3a3',
                borderDash: [5, 5],
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: 'y'
            });
        }

        if (type === 'imu' || type === 'merged') {
            const imuSeriesA = dataA.imu_data.map(d => d[imuMetric] || 0);
            const imuSeriesB = dataB.imu_data.map(d => d[imuMetric] || 0);
            
            if (labels.length === 0) {
                const maxLen = Math.max(imuSeriesA.length, imuSeriesB.length);
                labels = Array.from({ length: maxLen }, (_, i) => i);
            }

            datasets.push({
                label: `${nameA} (${imuMetric})`,
                data: imuSeriesA,
                borderColor: '#0d6efd',
                borderWidth: 1.5,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: type === 'merged' ? 'y1' : 'y'
            });
            datasets.push({
                label: `${nameB} (${imuMetric})`,
                data: imuSeriesB,
                borderColor: '#6c757d',
                borderDash: [3, 3],
                borderWidth: 1.5,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: type === 'merged' ? 'y1' : 'y'
            });
        }

        window.cmpChartInstance = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: { display: true, text: 'Skeleton Angle (°)' }
                    },
                    y1: {
                        type: 'linear',
                        display: type === 'merged',
                        position: 'right',
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: 'IMU Metric' }
                    },
                    x: { title: { display: true, text: 'Frame / Time' } }
                }
            }
        });
    }

    function renderComparisonTable(dataA, dataB, type, joint, imuMetric) {
        const tbody = document.getElementById('diffTable');
        const stats = document.getElementById('diffStats');
        
        let html = '';
        if (type === 'skeleton' || type === 'merged') {
            const valsA = dataA.pose_data.map(d => d[joint]).filter(v => v != null);
            const valsB = dataB.pose_data.map(d => d[joint]).filter(v => v != null);
            
            const meanA = (valsA.reduce((a,b)=>a+b,0)/valsA.length).toFixed(1);
            const meanB = (valsB.reduce((a,b)=>a+b,0)/valsB.length).toFixed(1);
            const maxA = Math.max(...valsA).toFixed(1);
            const maxB = Math.max(...valsB).toFixed(1);
            
            html += `
                <tr>
                    <td class="fw-semibold">${joint.toUpperCase()} ANGLE</td>
                    <td class="mono">${meanA}</td>
                    <td class="mono">${meanB}</td>
                    <td class="mono ${meanB-meanA > 0 ? 'text-success' : 'text-danger'}">${(meanB-meanA).toFixed(1)}</td>
                    <td class="mono">${maxA}</td>
                    <td class="mono">${maxB}</td>
                    <td class="mono ${maxB-maxA > 0 ? 'text-success' : 'text-danger'}">${(maxB-maxA).toFixed(1)}</td>
                </tr>
            `;
        }
        
        if (type === 'imu' || type === 'merged') {
            const valsA = dataA.imu_data.map(d => d[imuMetric]).filter(v => v != null);
            const valsB = dataB.imu_data.map(d => d[imuMetric]).filter(v => v != null);
            
            if (valsA.length > 0 && valsB.length > 0) {
                const meanA = (valsA.reduce((a,b)=>a+b,0)/valsA.length).toFixed(2);
                const meanB = (valsB.reduce((a,b)=>a+b,0)/valsB.length).toFixed(2);
                const maxA = Math.max(...valsA).toFixed(2);
                const maxB = Math.max(...valsB).toFixed(2);
                
                html += `
                    <tr>
                        <td class="fw-semibold">${imuMetric.toUpperCase()}</td>
                        <td class="mono">${meanA}</td>
                        <td class="mono">${meanB}</td>
                        <td class="mono">${(meanB-meanA).toFixed(2)}</td>
                        <td class="mono">${maxA}</td>
                        <td class="mono">${maxB}</td>
                        <td class="mono">${(maxB-maxA).toFixed(2)}</td>
                    </tr>
                `;
            }
        }
        tbody.innerHTML = html || '<tr><td colspan="7" class="text-center">無可比對數據</td></tr>';

        // Summary Stats (Placeholder for gait metrics if available)
        stats.innerHTML = ''; // Clear for now
    }
});
