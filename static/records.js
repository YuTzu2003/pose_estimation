document.addEventListener('DOMContentLoaded', () => {
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
});
