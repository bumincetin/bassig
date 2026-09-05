/* BASSIGNANA EPC CONTROL — local UI helpers.
   Vanilla JS only. Chart.js is bundled locally; nothing is fetched from a CDN. */
(function () {
  'use strict';

  var PALETTE = {
    navy: '#0b3d5c',
    amber: '#f5b301',
    green: '#198754',
    red: '#dc3545',
    blue: '#0d6efd',
    grey: '#8c9daa',
    teal: '#0dcaf0',
    purple: '#6f42c1'
  };
  var SERIES = [PALETTE.navy, PALETTE.amber, PALETTE.green, PALETTE.red,
                PALETTE.blue, PALETTE.teal, PALETTE.purple, PALETTE.grey];

  if (window.Chart) {
    Chart.defaults.font.family =
      "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = '#4a5b6b';
    Chart.defaults.animation = false;          // site tool: no decorative motion
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
  }

  function el(id) { return document.getElementById(id); }

  function shortDates(labels) {
    return (labels || []).map(function (value) {
      if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return value.slice(8, 10) + '/' + value.slice(5, 7);
      }
      return value;
    });
  }

  function makeChart(id, config) {
    var node = el(id);
    if (!node || !window.Chart) { return null; }
    return new Chart(node.getContext('2d'), config);
  }

  window.BAS = {
    palette: PALETTE,
    series: SERIES,

    line: function (id, labels, datasets, options) {
      return makeChart(id, {
        type: 'line',
        data: {
          labels: shortDates(labels),
          datasets: datasets.map(function (set, index) {
            return Object.assign({
              borderColor: SERIES[index % SERIES.length],
              backgroundColor: SERIES[index % SERIES.length] + '22',
              borderWidth: 2,
              pointRadius: set.data && set.data.length > 40 ? 0 : 2,
              tension: 0.15,
              spanGaps: true
            }, set);
          })
        },
        options: Object.assign({
          scales: { y: { beginAtZero: true } },
          interaction: { mode: 'index', intersect: false }
        }, options || {})
      });
    },

    bar: function (id, labels, datasets, options) {
      return makeChart(id, {
        type: 'bar',
        data: {
          labels: shortDates(labels),
          datasets: datasets.map(function (set, index) {
            return Object.assign({
              backgroundColor: SERIES[index % SERIES.length],
              borderWidth: 0
            }, set);
          })
        },
        options: Object.assign({ scales: { y: { beginAtZero: true } } }, options || {})
      });
    },

    hbar: function (id, labels, values, colour, options) {
      return makeChart(id, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{ data: values, backgroundColor: colour || PALETTE.navy, borderWidth: 0 }]
        },
        options: Object.assign({
          indexAxis: 'y',
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true } }
        }, options || {})
      });
    },

    doughnut: function (id, labels, values, options) {
      return makeChart(id, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: values,
            backgroundColor: labels.map(function (_, i) { return SERIES[i % SERIES.length]; }),
            borderWidth: 1,
            borderColor: '#fff'
          }]
        },
        options: Object.assign({
          cutout: '58%',
          plugins: { legend: { position: 'right' } }
        }, options || {})
      });
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    // Auto-submit filter forms when a select changes.
    document.querySelectorAll('[data-autosubmit] select, [data-autosubmit] input[type=date]')
      .forEach(function (node) {
        node.addEventListener('change', function () {
          var form = node.closest('form');
          if (form) { form.submit(); }
        });
      });

    // Confirm destructive actions.
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (!window.confirm(form.getAttribute('data-confirm'))) {
          event.preventDefault();
        }
      });
    });

    // Client-side table filter boxes.
    document.querySelectorAll('[data-filter-table]').forEach(function (input) {
      input.addEventListener('input', function () {
        var table = document.querySelector(input.getAttribute('data-filter-table'));
        if (!table) { return; }
        var needle = input.value.toLowerCase().trim();
        table.querySelectorAll('tbody tr').forEach(function (row) {
          row.style.display = !needle || row.textContent.toLowerCase().indexOf(needle) !== -1
            ? '' : 'none';
        });
      });
    });

    // Print buttons.
    document.querySelectorAll('[data-print]').forEach(function (button) {
      button.addEventListener('click', function () { window.print(); });
    });

    // Keep the daily-diary quantity helper honest about zero division.
    document.querySelectorAll('[data-achievement]').forEach(function (box) {
      var planned = box.querySelector('[name=planned_quantity]');
      var actual = box.querySelector('[name=actual_quantity]');
      var out = box.querySelector('[data-achievement-out]');
      // The labels are translated by the template; English is only a fallback.
      var labelNone = (out && out.getAttribute('data-label-none'))
        || 'Achievement: not calculable (no planned quantity)';
      var labelValue = (out && out.getAttribute('data-label-value')) || 'Achievement: {value}%';
      function update() {
        if (!out) { return; }
        var p = parseFloat(planned && planned.value);
        var a = parseFloat(actual && actual.value);
        if (!isFinite(p) || p === 0 || !isFinite(a)) {
          out.textContent = labelNone;
          return;
        }
        out.textContent = labelValue.replace('{value}', (a / p * 100).toFixed(1));
      }
      [planned, actual].forEach(function (node) {
        if (node) { node.addEventListener('input', update); }
      });
      update();
    });

    // Fill dependent fields when a WBS activity is picked in the diary.
    document.querySelectorAll('[data-activity-picker]').forEach(function (select) {
      select.addEventListener('change', function () {
        var option = select.options[select.selectedIndex];
        if (!option) { return; }
        var form = select.closest('form');
        if (!form) { return; }
        ['activity_name', 'work_package', 'unit', 'total_required_quantity'].forEach(function (name) {
          var field = form.querySelector('[name=' + name + ']');
          var value = option.getAttribute('data-' + name.replace(/_/g, '-'));
          if (field && value && !field.value) { field.value = value; }
        });
      });
    });
  });
})();
