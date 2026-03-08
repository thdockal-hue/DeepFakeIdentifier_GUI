// Vercel Serverless Function — Claude AI image analysis
// Deployed at: /api/analyze
// Works both locally (via server.js) and on Vercel (auto-detected api/ folder)

const Anthropic = require('@anthropic-ai/sdk');

const PROMPT = `You are a forensic image analyst specializing in deepfake and AI-generated image detection. Analyze this image carefully.

Provide your analysis as a JSON object with exactly these keys:
- "verdict": one of "LIKELY_REAL", "SUSPICIOUS", or "LIKELY_FAKE"
- "confidenceScore": integer 0-100 (0=definitely real, 100=definitely fake)
- "confidence": "LOW", "MEDIUM", or "HIGH"
- "generationMethod": string describing likely method (e.g. "GAN face generation", "Stable Diffusion", "Gemini image generation", "Face swap", "Authentic photograph", etc.)
- "anomalies": array of strings listing specific visual artifacts or inconsistencies observed
- "keyEvidence": array of exactly 3 strings — the strongest evidence points
- "summary": 1-2 sentence professional summary of your assessment
- "skinTexture": "Natural" | "Abnormal" | "N/A"
- "lightingConsistency": "Consistent" | "Inconsistent" | "N/A"
- "backgroundArtifacts": "None" | "Minor" | "Significant" | "N/A"
- "faceSymmetry": "Natural" | "Unnatural" | "N/A"

Respond ONLY with the JSON object, no markdown fences, no other text.`;

module.exports = async function handler(req, res) {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { imageBase64, mediaType } = req.body;
  if (!imageBase64 || !mediaType) {
    return res.status(400).json({ error: 'Missing imageBase64 or mediaType' });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY not configured on server' });
  }

  try {
    const client = new Anthropic({ apiKey });
    const message = await client.messages.create({
      model: 'claude-opus-4-6',
      max_tokens: 1024,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mediaType, data: imageBase64 } },
          { type: 'text', text: PROMPT }
        ]
      }]
    });

    const text = message.content[0].text.trim();
    try {
      return res.json({ success: true, analysis: JSON.parse(text) });
    } catch {
      const match = text.match(/\{[\s\S]*\}/);
      if (match) return res.json({ success: true, analysis: JSON.parse(match[0]) });
      return res.json({ success: true, analysis: { summary: text, verdict: 'SUSPICIOUS', confidenceScore: 50 } });
    }
  } catch (err) {
    console.error('Claude API error:', err.message);
    return res.status(500).json({ error: err.message });
  }
};
