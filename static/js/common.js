document.addEventListener('DOMContentLoaded', () => {
  // Shared common logic, like global checkbox styling updates
  document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
    checkbox.addEventListener('change', (e) => {
      const card = e.target.closest('.check-card');
      if (card) {
        card.classList.toggle('is-checked', e.target.checked);
      }
    });
  });
});
