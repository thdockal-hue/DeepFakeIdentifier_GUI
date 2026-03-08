const express = require('express');
const Anthropic = require('@anthropic-ai/sdk');
const path = require('path');
const fs = require('fs');

// Load API key from .env.txt (or .env)
function loadEnv() {
  const candidates = ['.env.txt', '.env'];
  for (const f of candidates) {
    try {
      const content = fs.readFileSync(path.join(__dirname, f), 'utf8');
      content.split('\n').forEach(line => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) return;
        const eq = trimmed.indexOf('=');
        if (eq === -1) return;
        const key = trimmed.slice(0, eq).trim();
        const val = trimmed.slice(eq + 1).trim();
        if (!process.env[key]) process.env[key] = val;
      });
      console.log(`Loaded env from ${f}`);
      break;
    } catch { /* try next */ }
  }
}
loadEnv();

const app = express();
app.use(express.json({ limit: '25mb' }));
app.use(express.static(path.join(__dirname)));

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// ── Claude AI image analysis endpoint ─────────────────────
app.post('/api/analyze', async (req, res) => {
  const { imageBase64, mediaType } = req.body;

  if (!imageBase64 || !mediaType) {
    return res.status(400).json({ error: 'Missing imageBase64 or mediaType' });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured' });
  }

  const prompt = `You are a forensic image analyst specializing in deepfake and AI-generated image detection. Analyze this image carefully.

Provide your analysis as a JSON object with exactly these keys:
- "verdict": one of "LIKELY_REAL", "SUSPICIOUS", or "LIKELY_FAKE"
- "confidenceScore": integer 0-100 (0=definitely real, 100=definitely fake)
- "confidence": "LOW", "MEDIUM", or "HIGH"
- "generationMethod": string describing likely method (e.g. "GAN face generation", "Stable Diffusion", "Face swap", "Authentic photograph", etc.)
- "anomalies": array of strings listing specific visual artifacts or inconsistencies observed
- "keyEvidence": array of exactly 3 strings — the strongest evidence points
- "summary": 1-2 sentence professional summary of your assessment
- "skinTexture": "Natural" | "Abnormal" | "N/A"
- "lightingConsistency": "Consistent" | "Inconsistent" | "N/A"
- "backgroundArtifacts": "None" | "Minor" | "Significant" | "N/A"
- "faceSymmetry": "Natural" | "Unnatural" | "N/A"

Respond ONLY with the JSON object, no markdown fences, no other text.`;

  try {
    const message = await client.messages.create({
      model: 'claude-opus-4-6',
      max_tokens: 1024,
      messages: [{
        role: 'user',
        content: [
          {
            type: 'image',
            source: { type: 'base64', media_type: mediaType, data: imageBase64 }
          },
          { type: 'text', text: prompt }
        ]
      }]
    });

    const text = message.content[0].text.trim();
    try {
      const analysis = JSON.parse(text);
      res.json({ success: true, analysis });
    } catch {
      // Try to extract JSON if model wrapped it
      const match = text.match(/\{[\s\S]*\}/);
      if (match) {
        res.json({ success: true, analysis: JSON.parse(match[0]) });
      } else {
        res.json({ success: true, analysis: { summary: text, verdict: 'SUSPICIOUS', confidenceScore: 50 } });
      }
    }
  } catch (err) {
    console.error('Claude API error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`\n🔍 Deepfake Identifier running at http://localhost:${PORT}\n`);
});
