# DeepFake Identifier GUI

A browser-based web application for detecting AI-generated and manipulated images using a 5-module forensic analysis pipeline.

## Detection Modules

| Module | Weight | Method |
|--------|--------|--------|
| Metadata Analysis | 10% | EXIF, PNG chunks, AI software signatures, quantization tables |
| Pixel & Artifact Analysis | 20% | Noise uniformity, edge kurtosis, color channel correlation, block artifacts |
| AI Vision Analysis | 35% | Claude Vision — face boundaries, lighting, skin texture, eye/teeth anomalies |
| Frequency Domain Analysis | 20% | FFT GAN fingerprints, checkerboard artifacts, power spectrum slope |
| Statistical / ELA Analysis | 15% | Error Level Analysis, copy-move detection, Benford's law |

## Score Interpretation

| Score | Verdict |
|-------|---------|
| 0 – 25 | AUTHENTIC |
| 26 – 50 | SUSPICIOUS |
| 51 – 75 | PROBABLE_DEEPFAKE |
| 76 – 100 | HIGH_CONFIDENCE_DEEPFAKE |

## Setup

```bash
pip install -r requirements.txt
```

To enable the AI Vision module (35% weight):
```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

## Run

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

## API

```bash
# Analyze an image
curl -X POST http://localhost:5000/analyze -F "image=@photo.jpg"

# Health check
curl http://localhost:5000/health

# Module info
curl http://localhost:5000/modules
```

## Supported Image Formats

JPEG, PNG, WebP, BMP, TIFF — max 20 MB
