# Deepfake Identifier — Project Guide

AI-powered forensic image analysis tool. Combines client-side pixel algorithms with Claude AI vision analysis to detect synthetic/AI-generated images.

## Stack
- **Frontend**: Single-page HTML/CSS/JS (no framework, no build step)
- **Backend**: Node.js + Express (local dev) / Vercel Serverless (production)
- **AI**: Anthropic Claude claude-opus-4-6 Vision API

## Local Development

**Requires Node.js** — download from https://nodejs.org (LTS version)

```bash
cd deepfake-detector
npm install        # one-time setup
npm start          # → http://localhost:3000
```

## File Structure
```
deepfake-detector/
├── index.html         # Complete SPA frontend
├── server.js          # Express backend for local dev (reads .env.txt)
├── package.json       # Dependencies (@anthropic-ai/sdk, express)
├── vercel.json        # Vercel deployment config
├── api/
│   └── analyze.js     # Vercel serverless function (production API)
├── impressum.html     # German legal imprint (TMG §5) — fill placeholders!
├── datenschutz.html   # GDPR privacy policy — fill placeholders!
├── .gitignore         # Excludes .env.txt and node_modules
├── .env.txt           # API key — NEVER commit this file
└── CLAUDE.md          # This file
```

## Environment
`.env.txt` must contain:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
```
The server auto-detects `.env.txt` or `.env` — no renaming needed.

## Analytics Methods

### Client-side (runs in browser, no data sent)
1. **Error Level Analysis (ELA)** — PNG/WebP-aware: compares JPEG@85% vs JPEG@60%, measures ELA uniformity, weight 1.5
2. **Noise Analysis** — Laplacian high-pass filter + patch-level noise uniformity, weight 2.2
3. **Frequency Analysis** — spatial periodicity / autocorrelation at lags 8/16/32, weight 0.9
4. **Color Coherence** — hue entropy + saturation variance, weight 1.0
5. **Edge Integrity** — Sobel edge density coefficient of variation, weight 1.2
6. **Metadata Presence** — EXIF/XMP binary header scan (bare PNG = 78, strong AI signal), weight 2.5
7. **Texture Complexity (LBP)** — local binary pattern entropy, calibrated at 0.62, weight 1.8
8. **Sharpness Uniformity** — local variance map across 28×28 patches, CoV analysis, weight 1.4
9. **Channel Statistics** — RGB skewness anomaly detection, weight 0.8
10. **Symmetry Analysis** — bilateral pixel symmetry deviation, weight 0.7

### Server-side (Claude AI Vision)
- Claude claude-opus-4-6 analyzes: skin texture, lighting, face symmetry, background artifacts, generation method

### Verdict Thresholds
- **< 26%** → LIKELY REAL
- **26–49%** → SUSPICIOUS
- **≥ 50%** → LIKELY DEEPFAKE

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

---

## GitHub Repository
**https://github.com/thdockal-hue/DeepFakeIdentifier_GUI**
- Account: `thdockal-hue`
- Default branch: `main`
- Auto-deploys to Vercel on every push to `main`

To push updates:
```bash
git add .
git commit -m "your message"
git push origin main
# Vercel deploys automatically within ~30 seconds
```

---

## Deployment — deepfakeindicator.com

**Domain provider**: Domain Factory (df.eu)
**Hosting**: Vercel (free tier)

### Step 1 — Deploy to Vercel
1. Go to **https://vercel.com** → Sign in with GitHub (`thdockal-hue`)
2. **Add New Project** → Import `DeepFakeIdentifier_GUI`
3. Framework Preset: **Other** · Root Directory: empty · Click **Deploy**
4. After deploy: **Settings → Environment Variables** → Add:
   - Name: `ANTHROPIC_API_KEY`
   - Value: `sk-ant-api03-...` (from your `.env.txt`)
5. **Deployments → Redeploy** (so the API key takes effect)

### Step 2 — Connect domain at df.eu
1. In Vercel: **Settings → Domains** → add `deepfakeindicator.com` → click **Add**
2. Vercel shows the required DNS records — add these in **df.eu DNS Settings**:

| Type  | Name | Value                  |
|-------|------|------------------------|
| A     | `@`  | `76.76.21.21`          |
| CNAME | `www`| `cname.vercel-dns.com` |

3. Delete any existing A record for `@` in df.eu first
4. Save → wait 5–30 min for DNS propagation
5. Vercel auto-issues free SSL certificate

**Result**: https://deepfakeindicator.com ✓

### Step 3 — Fill legal placeholders (required before go-live!)
Edit `impressum.html` and `datenschutz.html` — replace all `[PLATZHALTER]`:

| Placeholder | Replace with |
|---|---|
| `[VORNAME NACHNAME]` | Your real name |
| `[STRASSE HAUSNUMMER]` | Your street address |
| `[PLZ ORT]` | Postal code + city |
| `[IHRE-EMAIL@DOMAIN.DE]` | Your contact email |
| `[TELEFONNUMMER]` | Your phone number |

Then push:
```bash
git add impressum.html datenschutz.html
git commit -m "Add legal contact info"
git push origin main
```

---

## Legal Pages
- `impressum.html` — German legal imprint (required by TMG §5 for German operators)
- `datenschutz.html` — GDPR/DSGVO privacy policy
- Cookie banner — built into `index.html`, consent stored in `localStorage`
