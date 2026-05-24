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

    let currentOffset = 0;
    const compareControls = document.getElementById('compareControls');
    const offsetDisplay = document.getElementById('offsetDisplay');

    async function requestComparison(alignMax = false) {
        const idA = recordA.value;
        const idB = recordB.value;
        const type = compareType.value;
        const joint = document.getElementById('jointSelect').value;
        const imuMetric = document.getElementById('imuMetricSelect').value;
        const selectedMetric = (type === 'skeleton') ? joint : imuMetric;

        runCompare.disabled = true;
        if (!alignMax) runCompare.textContent = "正在產製圖表...";

        try {
            const response = await fetch('/api/compare_charts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id_a: idA,
                    id_b: idB,
                    type: type,
                    metric: selectedMetric,
                    offset: currentOffset,
                    align_max: alignMax
                })
            });

            const result = await response.json();
            
            if (response.ok) {
                document.getElementById('chartImgA').src = result.chart_a;
                document.getElementById('chartImgB').src = result.chart_b;
                document.getElementById('chartImgMerged').src = result.merged;
                
                currentOffset = result.offset;
                offsetDisplay.textContent = `Offset: ${currentOffset}`;

                cmpResult.hidden = false;
                compareControls.style.setProperty('display', 'flex', 'important');
                if (!alignMax) cmpResult.scrollIntoView({ behavior: 'smooth' });
            } else {
                alert("產製比對圖表失敗: " + result.error);
            }
        } catch (err) {
            console.error("Compare error:", err);
            alert("與伺服器連線時發生錯誤。");
        } finally {
            runCompare.disabled = false;
            runCompare.textContent = "執行比對 / RUN COMPARE";
        }
    }

    runCompare.addEventListener('click', () => {
        if (!recordA.value || !recordB.value) {
            alert("請先選擇兩組紀錄進行比對。");
            return;
        }
        currentOffset = 0;
        requestComparison();
    });

    document.getElementById('btnShiftLeft').onclick = () => {
        currentOffset -= 1;
        requestComparison();
    };

    document.getElementById('btnShiftRight').onclick = () => {
        currentOffset += 1;
        requestComparison();
    };

    document.getElementById('btnAlignMax').onclick = () => {
        requestComparison(true);
    };
});
