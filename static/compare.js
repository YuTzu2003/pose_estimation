document.addEventListener('DOMContentLoaded', () => {
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
    
    tbody.innerHTML = `
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
    `;

    const diffStats = document.getElementById('diffStats');
    if (diffStats) {
      diffStats.innerHTML = `
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
      `;
    }
  }
});
