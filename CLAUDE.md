# Deepfake Identifier — Project Guide

AI-powered forensic image analysis tool. Combines client-side pixel algorithms with Claude AI vision analysis to detect synthetic/AI-generated images.

## Stack
- **Frontend**: Single-page HTML/CSS/JS (no framework, no build step)
- **Backend**: Node.js + Express (serves static files + proxies Claude API)
- **AI**: Anthropic Claude claude-opus-4-6 Vision API

## Setup
```bash
npm install
npm start
# → http://localhost:3000
```

## File Structure
```
deepfake-detector/
├── index.html       # Complete SPA frontend
├── server.js        # Express backend (API proxy)
├── package.json     # Dependencies
├── .env.txt         # API key (ANTHROPIC_API_KEY=sk-ant-...)
└── CLAUDE.md        # This file
```

## Environment
`.env.txt` must contain:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

## Analytics Methods

### Client-side (runs in browser, no data sent)
1. **Error Level Analysis (ELA)** — JPEG recompression diff, weight 2.0
2. **Noise Analysis** — luminance residual noise floor, weight 1.5
3. **Frequency Analysis** — spatial periodicity / autocorrelation, weight 1.2
4. **Color Coherence** — hue entropy + saturation variance, weight 1.0
5. **Edge Integrity** — Sobel edge density coefficient of variation, weight 1.3
6. **Metadata Presence** — EXIF/XMP binary header scan, weight 0.8
7. **Texture Complexity (LBP)** — local binary pattern entropy, weight 1.1
8. **DCT Block Artifacts** — 8×8 block boundary discontinuity, weight 0.9
9. **Channel Statistics** — RGB skewness / kurtosis anomaly, weight 0.7
10. **Symmetry Analysis** — bilateral pixel symmetry deviation, weight 0.6

### Server-side (Claude AI Vision)
- Claude claude-opus-4-6 analyzes the image for visual artifacts, inconsistencies, generation method

## Design System
- **Style**: Apple-inspired — clean, minimal, white backgrounds
- **Font**: `-apple-system, BlinkMacSystemFont, SF Pro, Helvetica Neue, system-ui`
- **Accent**: `#0071e3` (Apple blue)
- **Background**: `#ffffff` / `#f5f5f7`
- **Text**: `#1d1d1f` primary, `#6e6e73` secondary
- **Cards**: white + subtle shadow + 18px radius

## API Endpoint
**POST /api/analyze**
```json
Request:  { "imageBase64": "...", "mediaType": "image/jpeg" }
Response: { "success": true, "analysis": { "verdict": "LIKELY_FAKE", "confidence": "HIGH", ... } }
```

## Deployment (Phase 2 — after testing)
Target domain: deepfakeidentifier.com
See deployment notes in a separate DEPLOY.md once Phase 1 is stable.
