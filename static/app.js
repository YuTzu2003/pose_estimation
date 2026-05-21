document.addEventListener('DOMContentLoaded', () => {
  // --- index.html ---
  const fileInput = document.getElementById('fileInput');
  const fileNameDisplay = document.getElementById('fileName');
  const fileDrop = document.getElementById('fileDrop');
  const uploadForm = document.getElementById('uploadForm');

  if (fileInput && fileNameDisplay) {
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        fileNameDisplay.textContent = e.target.files[0].name;
        fileNameDisplay.style.color = 'var(--fg)';
      } else {
        fileNameDisplay.textContent = '未選取檔案';
        fileNameDisplay.style.color = 'var(--muted)';
      }
    });
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
    uploadForm.addEventListener('submit', (e) => {
      e.preventDefault();
      alert('已送出分析請求（前端示範）。往下滾動至「分析結果預覽」查看。');
      const resultSec = document.getElementById('result');
      if (resultSec) resultSec.scrollIntoView({ behavior: 'smooth' });
    });
  }

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

  // --- records.html ---
  const recordsList = document.getElementById('recordsList');
  if (recordsList) {
    const records = [
      { id: 1, name: 'Lin C.H.', session: '2026 春季測驗 #2', date: '2026-05-20', cadence: 186, speed: 6.62 },
      { id: 2, name: 'Wang Y.T.', session: '常規訓練', date: '2026-05-18', cadence: 178, speed: 6.10 },
      { id: 3, name: 'Lin C.H.', session: '2026 春季測驗 #1', date: '2026-04-10', cadence: 184, speed: 6.55 }
    ];

    document.getElementById('statTotal').textContent = '248';
    document.getElementById('statAthletes').textContent = '12';
    document.getElementById('resultCount').textContent = `共 ${records.length} 筆紀錄`;

    let html = '';
    records.forEach(r => {
      html += `
        <div class="tile d-flex align-items-center gap-4 mb-2" style="padding: 1rem 1.25rem;">
          <div>
            <div class="fw-semibold">${r.name}</div>
            <div class="small text-muted">${r.session}</div>
          </div>
          <div class="ms-auto d-none d-sm-block text-end">
            <div class="mono small">${r.cadence} spm</div>
            <div class="mono small text-muted">CADENCE</div>
          </div>
          <div class="d-none d-md-block text-end" style="min-width: 80px;">
            <div class="mono small">${r.speed} m/s</div>
            <div class="mono small text-muted">SPEED</div>
          </div>
          <div class="mono small text-muted ms-3">${r.date}</div>
          <a href="#" class="btn btn-sm btn-outline-dark ms-3">查看</a>
        </div>
      `;
    });
    recordsList.innerHTML = html;
  }

  // --- compare.html ---
  const jointPicker = document.getElementById('jointPicker');
  if (jointPicker) {
    const joints = [
      { id: 'hip', name: '髖關節 Hip', desc: '軀幹與大腿的夾角' },
      { id: 'knee', name: '膝關節 Knee', desc: '大腿與小腿的夾角' },
      { id: 'ankle', name: '踝關節 Ankle', desc: '小腿與腳掌的夾角' },
      { id: 'shoulder', name: '肩關節 Shoulder', desc: '軀幹與上臂的夾角' },
      { id: 'elbow', name: '肘關節 Elbow', desc: '上臂與前臂的夾角' }
    ];
    let jointHtml = '';
    joints.forEach((j, i) => {
      jointHtml += `
        <div class="col-md-6 col-lg-4">
          <label class="check-card ${i === 1 ? 'is-checked' : ''}">
            <input type="radio" class="form-check-input" name="joint" value="${j.id}" ${i === 1 ? 'checked' : ''} />
            <div class="ck-num">J-0${i+1}</div>
            <div class="ck-title">${j.name}</div>
            <div class="ck-desc">${j.desc}</div>
          </label>
        </div>
      `;
    });
    jointPicker.innerHTML = jointHtml;

    // radio button styling updates
    jointPicker.addEventListener('change', (e) => {
      if (e.target.name === 'joint') {
        document.querySelectorAll('input[name="joint"]').forEach(radio => {
          radio.closest('.check-card').classList.toggle('is-checked', radio.checked);
        });
      }
    });

    const runCompare = document.getElementById('runCompare');
    if (runCompare) {
      runCompare.addEventListener('click', () => {
        document.getElementById('cmpResult').hidden = false;
        document.getElementById('cmpResult').scrollIntoView({ behavior: 'smooth' });
        renderCompareChart();
        renderCompareTable();
      });
    }

    const resetCompare = document.getElementById('resetCompare');
    if (resetCompare) {
      resetCompare.addEventListener('click', () => {
        document.getElementById('cmpResult').hidden = true;
      });
    }
  }

  function renderCompareChart() {
    const ctx = document.getElementById('cmpChart');
    if (!ctx) return;
    
    if (window.cmpChartInstance) {
        window.cmpChartInstance.destroy();
    }

    const labels = Array.from({ length: 100 }, (_, i) => i);
    const dataA = labels.map(i => 120 + Math.sin(i / 10) * 30 + Math.random() * 5);
    const dataB = labels.map(i => 122 + Math.sin(i / 10 + 0.2) * 28 + Math.random() * 5);

    window.cmpChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: '紀錄 A (2026 春季測驗 #2)',
            data: dataA,
            borderColor: '#171717',
            backgroundColor: '#171717',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0
          },
          {
            label: '紀錄 B (2026 春季測驗 #1)',
            data: dataB,
            borderColor: '#a3a3a3',
            borderDash: [5, 5],
            backgroundColor: '#a3a3a3',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            position: 'top',
            labels: {
              usePointStyle: true,
              boxWidth: 8
            }
          }
        },
        scales: {
          y: {
            title: { display: true, text: 'Angle (°)' }
          },
          x: {
            title: { display: true, text: 'Frame (60fps)' }
          }
        }
      }
    });
  }

  function renderCompareTable() {
    const tbody = document.getElementById('diffTable');
    if (!tbody) return;
    
    tbody.innerHTML = \`
      <tr>
        <td class="fw-semibold">Knee Flexion (Max)</td>
        <td class="mono">152.4</td>
        <td class="mono">148.1</td>
        <td class="mono text-success">+4.3</td>
        <td class="mono">160.2</td>
        <td class="mono">156.8</td>
        <td class="mono text-success">+3.4</td>
      </tr>
      <tr>
        <td class="fw-semibold">Knee Extension (Min)</td>
        <td class="mono">12.5</td>
        <td class="mono">15.2</td>
        <td class="mono text-danger">-2.7</td>
        <td class="mono">10.1</td>
        <td class="mono">11.5</td>
        <td class="mono text-danger">-1.4</td>
      </tr>
    \`;

    const diffStats = document.getElementById('diffStats');
    if (diffStats) {
      diffStats.innerHTML = \`
        <div class="col-6 col-md-3">
          <div class="stat">
            <div class="label">Δ STRIDE LEN</div>
            <div class="value num text-success">+0.12<span class="unit">m</span></div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="stat">
            <div class="label">Δ CADENCE</div>
            <div class="value num text-success">+2<span class="unit">spm</span></div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="stat">
            <div class="label">Δ SPEED</div>
            <div class="value num text-success">+0.07<span class="unit">m/s</span></div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="stat">
            <div class="label">Δ CONTACT</div>
            <div class="value num text-danger">-5<span class="unit">ms</span></div>
          </div>
        </div>
      \`;
    }
  }

  // checkbox styling updates
  document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
    checkbox.addEventListener('change', (e) => {
      const card = e.target.closest('.check-card');
      if (card) {
        card.classList.toggle('is-checked', e.target.checked);
      }
    });
  });
});