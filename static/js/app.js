/**
 * DeepFake Identifier — Frontend Application
 * 3-step wizard: Welcome → Upload → Results
 */

'use strict';

/* ─────────────────────────────────────────────
   Constants
───────────────────────────────────────────── */
const MAX_FILE_SIZE  = 20 * 1024 * 1024; // 20 MB
const ALLOWED_TYPES  = ['image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/tiff'];
const PREVIEW_INIT   = 4; // show first N findings before "show all"

/* ─────────────────────────────────────────────
   DOM references
───────────────────────────────────────────── */
const dropZone     = document.getElementById('drop-zone');
const fileInput    = document.getElementById('file-input');
const browseBtn    = document.getElementById('browse-btn');
const dzIdle       = document.getElementById('dz-idle');
const dzDragging   = document.getElementById('dz-dragging');
const previewPanel = document.getElementById('preview-panel');
const previewImg   = document.getElementById('preview-img');
const previewFname = document.getElementById('preview-filename');
const previewDets  = document.getElementById('preview-details');
const clearBtn     = document.getElementById('clear-btn');
const analyzeBtn   = document.getElementById('analyze-btn');
const uploadErr    = document.getElementById('upload-error');
const uploadErrMsg = document.getElementById('upload-error-msg');

// Step 3 states
const stateLoading = document.getElementById('state-loading');
const stateError   = document.getElementById('state-error');
const stateSuccess = document.getElementById('state-success');
const errorMsgText = document.getElementById('error-msg-text');

// Results DOM
const resultImg      = document.getElementById('result-img');
const resultImgLabel = document.getElementById('result-img-label');
const gaugeArc       = document.getElementById('gauge-arc');
const gaugeNumber    = document.getElementById('gauge-number');
const verdictBadge   = document.getElementById('verdict-badge');
const verdictType    = document.getElementById('verdict-type');
const verdictConf    = document.getElementById('verdict-conf');
const verdictDesc    = document.getElementById('verdict-desc');
const verdictTypeExp = document.getElementById('verdict-type-exp');
const moduleBreakdown= document.getElementById('module-breakdown');
const findingsList   = document.getElementById('findings-list');
const findingsToggle = document.getElementById('findings-toggle');
const infoGrid       = document.getElementById('info-grid');
const resultSummary  = document.getElementById('state-success');

/* ─────────────────────────────────────────────
   State
───────────────────────────────────────────── */
let selectedFile     = null;
let selectedDataURL  = null;
let allFindingsVisible = false;

/* ─────────────────────────────────────────────
   Step Navigation
───────────────────────────────────────────── */
function goToStep(n) {
  document.querySelectorAll('.step-section').forEach((el, i) => {
    el.classList.toggle('active', i + 1 === n);
  });
  document.querySelectorAll('.step-dot').forEach((dot, i) => {
    dot.classList.remove('active', 'done');
    if (i + 1 === n)  dot.classList.add('active');
    if (i + 1 < n)    dot.classList.add('done');
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ─────────────────────────────────────────────
   Drag & Drop
───────────────────────────────────────────── */
dropZone.addEventListener('dragenter', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
  dzIdle.classList.add('hidden');
  dzDragging.classList.remove('hidden');
});

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
});

dropZone.addEventListener('dragleave', (e) => {
  if (!dropZone.contains(e.relatedTarget)) {
    dropZone.classList.remove('drag-over');
    dzIdle.classList.remove('hidden');
    dzDragging.classList.add('hidden');
  }
});

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  dzIdle.classList.remove('hidden');
  dzDragging.classList.add('hidden');
  if (e.dataTransfer.files.length > 0) {
    processFile(e.dataTransfer.files[0]);
  }
});

dropZone.addEventListener('click', (e) => {
  if (e.target !== browseBtn) fileInput.click();
});

dropZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    fileInput.click();
  }
});

browseBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.click();
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) processFile(fileInput.files[0]);
});

clearBtn.addEventListener('click', () => {
  clearFile();
});

/* ─────────────────────────────────────────────
   File Handling
───────────────────────────────────────────── */
function processFile(file) {
  hideUploadError();

  if (!ALLOWED_TYPES.includes(file.type)) {
    showUploadError(`Unsupported file type "${file.type}". Please upload a JPG, PNG, WebP, BMP, or TIFF image.`);
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    showUploadError(`File is too large (${fmtBytes(file.size)}). Maximum allowed size is 20 MB.`);
    return;
  }

  selectedFile = file;

  // Show preview via FileReader
  const reader = new FileReader();
  reader.onload = (e) => {
    selectedDataURL = e.target.result;
    previewImg.src = selectedDataURL;
    previewFname.textContent = file.name;
    previewDets.textContent = `${fmtBytes(file.size)} · ${file.type.split('/')[1].toUpperCase()}`;
    previewPanel.classList.remove('hidden');
    analyzeBtn.disabled = false;
  };
  reader.readAsDataURL(file);
}

function clearFile() {
  selectedFile    = null;
  selectedDataURL = null;
  fileInput.value = '';
  previewImg.src  = '';
  previewPanel.classList.add('hidden');
  analyzeBtn.disabled = true;
  hideUploadError();
}

function showUploadError(msg) {
  uploadErrMsg.textContent = msg;
  uploadErr.classList.remove('hidden');
}

function hideUploadError() {
  uploadErr.classList.add('hidden');
  uploadErrMsg.textContent = '';
}

/* ─────────────────────────────────────────────
   Analysis — Send to API
───────────────────────────────────────────── */
async function analyzeImage() {
  if (!selectedFile) return;

  // Switch to step 3, show loading
  goToStep(3);
  showResultState('loading');

  const formData = new FormData();
  formData.append('image', selectedFile);

  try {
    const response = await fetch('/analyze', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    renderResults(data);
    showResultState('success');

  } catch (err) {
    errorMsgText.textContent = err.message || 'Failed to reach the server. Is it running?';
    showResultState('error');
  }
}

function showResultState(state) {
  stateLoading.classList.add('hidden');
  stateError.classList.add('hidden');
  stateSuccess.classList.add('hidden');

  if (state === 'loading')  stateLoading.classList.remove('hidden');
  if (state === 'error')    stateError.classList.remove('hidden');
  if (state === 'success')  stateSuccess.classList.remove('hidden');
}

/* ─────────────────────────────────────────────
   Render Results
───────────────────────────────────────────── */
function renderResults(data) {
  const score   = data.deepfake_score || 0;
  const verdict = data.verdict || 'UNKNOWN';

  // ── Uploaded image ──
  resultImg.src        = selectedDataURL || '';
  resultImgLabel.textContent = selectedFile ? selectedFile.name : '';

  // ── Gauge ──
  animateGauge(score, verdict);

  // ── Verdict badge ──
  verdictBadge.textContent = fmtVerdict(verdict);
  verdictBadge.className   = 'verdict-badge ' + verdictBadgeClass(verdict);

  verdictType.textContent   = fmtType(data.deepfake_type || 'UNKNOWN');
  verdictConf.textContent   = data.confidence || '—';
  verdictDesc.textContent   = data.verdict_description || '';
  verdictTypeExp.textContent = data.type_explanation || '';

  // ── Module breakdown ──
  renderModuleBreakdown(data.module_scores || {}, data.module_weights || {});

  // ── Findings ──
  renderFindings(data.findings || []);

  // ── Image info ──
  renderImageInfo(data.image_info || {}, data.timing || {}, data.analysis_summary || {});
}

/* ── Score gauge animation ── */
function animateGauge(score, verdict) {
  const CIRCUMFERENCE = 2 * Math.PI * 80; // r=80
  const pct    = Math.min(Math.max(score, 0), 100) / 100;
  const offset = CIRCUMFERENCE * (1 - pct);

  // Set score class on parent for stroke colour
  const wrap = document.querySelector('.result-summary');
  if (wrap) {
    wrap.classList.remove('score-authentic', 'score-suspicious', 'score-probable', 'score-high');
    wrap.classList.add(scoreClass(verdict));
  }

  // Animate number count-up
  let current = 0;
  const target = Math.round(score);
  const step   = Math.max(1, Math.ceil(target / 40));
  const timer  = setInterval(() => {
    current = Math.min(current + step, target);
    gaugeNumber.textContent = current;
    if (current >= target) clearInterval(timer);
  }, 28);

  // Animate arc (slight delay so transition fires after DOM paint)
  setTimeout(() => {
    gaugeArc.style.strokeDashoffset = offset;
  }, 60);
}

/* ── Module breakdown ── */
function renderModuleBreakdown(scores, weights) {
  const modules = [
    { key: 'metadata_analysis',    label: 'Metadata Analysis',        icon: '📋' },
    { key: 'artifact_analysis',    label: 'Pixel & Artifact',         icon: '🔬' },
    { key: 'ai_vision_analysis',   label: 'AI Vision',                icon: '🤖' },
    { key: 'frequency_analysis',   label: 'Frequency Domain',         icon: '📊' },
    { key: 'statistical_analysis', label: 'Statistical / ELA',        icon: '📈' },
  ];

  const weightKeys = {
    metadata_analysis:    'metadata',
    artifact_analysis:    'artifact',
    ai_vision_analysis:   'ai_vision',
    frequency_analysis:   'frequency',
    statistical_analysis: 'statistical',
  };

  moduleBreakdown.innerHTML = modules.map(({ key, label, icon }) => {
    const s    = scores[key] ?? 0;
    const wKey = weightKeys[key] || key;
    const w    = weights[wKey] !== undefined ? (weights[wKey] * 100).toFixed(0) : '—';
    const col  = scoreColorClass(s);

    return `
      <div class="mb-row">
        <div>
          <div class="mb-name">${icon} ${label}</div>
          <div class="mb-weight">Weight: ${w}%</div>
        </div>
        <div class="mb-track">
          <div class="mb-fill ${col}" data-target="${s}" style="width:0%"></div>
        </div>
        <div class="mb-score ${textColorClass(s)}">${s.toFixed(0)}</div>
      </div>
    `;
  }).join('');

  // Animate bars
  setTimeout(() => {
    moduleBreakdown.querySelectorAll('.mb-fill').forEach((bar) => {
      const target = parseFloat(bar.dataset.target) || 0;
      bar.style.width = target + '%';
    });
  }, 100);
}

/* ── Findings list ── */
function renderFindings(findings) {
  allFindingsVisible = false;
  findingsList.innerHTML = '';

  if (!findings.length) {
    findingsList.innerHTML = '<li class="finding-item"><span class="finding-text">No findings reported.</span></li>';
    findingsToggle.classList.add('hidden');
    return;
  }

  findingsToggle.classList.remove('hidden');
  findingsToggle.textContent = `Show all (${findings.length})`;

  findings.forEach((raw, i) => {
    const { tag, text } = parseFinding(raw);
    const li = document.createElement('li');
    li.className = 'finding-item' + (i >= PREVIEW_INIT ? ' hidden-finding' : '');
    li.innerHTML = `<span class="finding-tag">${tag}</span><span class="finding-text">${escapeHtml(text)}</span>`;
    findingsList.appendChild(li);
  });

  if (findings.length <= PREVIEW_INIT) findingsToggle.classList.add('hidden');
}

function toggleFindings() {
  allFindingsVisible = !allFindingsVisible;
  findingsList.querySelectorAll('.hidden-finding').forEach((li) => {
    li.classList.toggle('visible', allFindingsVisible);
    if (!allFindingsVisible) li.classList.remove('visible');
  });
  // Show hidden items or re-hide
  findingsList.querySelectorAll('.finding-item').forEach((li, i) => {
    if (i >= PREVIEW_INIT) {
      li.style.display = allFindingsVisible ? 'flex' : 'none';
    }
  });
  findingsToggle.textContent = allFindingsVisible ? 'Show less' : `Show all (${findingsList.children.length})`;
}

/* ── Image info ── */
function renderImageInfo(info, timing, summary) {
  const cells = [
    { label: 'Format',       value: info.format || '—' },
    { label: 'Dimensions',   value: info.width && info.height ? `${info.width} × ${info.height}` : '—' },
    { label: 'File Size',    value: info.file_size_bytes ? fmtBytes(info.file_size_bytes) : '—' },
    { label: 'Mode',         value: info.mode || '—' },
    { label: 'Modules Run',  value: summary.total_modules != null ? `${summary.modules_flagged} / ${summary.total_modules} flagged` : '—' },
    { label: 'AI Vision',    value: summary.ai_vision_available ? 'Active' : 'Skipped (no key)' },
  ];

  infoGrid.innerHTML = cells.map(({ label, value }) => `
    <div class="info-cell">
      <div class="info-cell-label">${label}</div>
      <div class="info-cell-value">${escapeHtml(String(value))}</div>
    </div>
  `).join('');
}

/* ─────────────────────────────────────────────
   Reset
───────────────────────────────────────────── */
function resetAll() {
  clearFile();
  goToStep(1);
}

/* ─────────────────────────────────────────────
   Helper functions
───────────────────────────────────────────── */
function fmtBytes(bytes) {
  if (bytes < 1024)        return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

function scoreClass(verdict) {
  if (!verdict) return '';
  const v = verdict.toUpperCase();
  if (v === 'AUTHENTIC')               return 'score-authentic';
  if (v === 'SUSPICIOUS')              return 'score-suspicious';
  if (v === 'PROBABLE_DEEPFAKE')       return 'score-probable';
  if (v === 'HIGH_CONFIDENCE_DEEPFAKE') return 'score-high';
  return '';
}

function verdictBadgeClass(verdict) {
  if (!verdict) return '';
  const v = verdict.toUpperCase();
  if (v === 'AUTHENTIC')               return 'badge-authentic';
  if (v === 'SUSPICIOUS')              return 'badge-suspicious';
  if (v === 'PROBABLE_DEEPFAKE')       return 'badge-probable';
  if (v === 'HIGH_CONFIDENCE_DEEPFAKE') return 'badge-high';
  return '';
}

function scoreColorClass(score) {
  if (score <= 25) return 'fill-green';
  if (score <= 50) return 'fill-yellow';
  if (score <= 75) return 'fill-orange';
  return 'fill-red';
}

function textColorClass(score) {
  if (score <= 25) return 'color-green';
  if (score <= 50) return 'color-yellow';
  if (score <= 75) return 'color-orange';
  return 'color-red';
}

function fmtVerdict(v) {
  const map = {
    'AUTHENTIC':               'Authentic',
    'SUSPICIOUS':              'Suspicious',
    'PROBABLE_DEEPFAKE':       'Probable Deepfake',
    'HIGH_CONFIDENCE_DEEPFAKE': 'High Confidence Deepfake',
  };
  return map[v] || v;
}

function fmtType(t) {
  return (t || '').replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function parseFinding(raw) {
  const m = raw.match(/^\[([^\]]+)\]\s*(.*)/s);
  if (m) return { tag: m[1], text: m[2] };
  return { tag: 'Info', text: raw };
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ─────────────────────────────────────────────
   CSS color helpers injected via JS
   (adds text color rules for mb-score)
───────────────────────────────────────────── */
(function injectColorHelpers() {
  const style = document.createElement('style');
  style.textContent = `
    .color-green  { color: var(--green); }
    .color-yellow { color: var(--yellow); }
    .color-orange { color: var(--orange); }
    .color-red    { color: var(--red); }
  `;
  document.head.appendChild(style);
})();
