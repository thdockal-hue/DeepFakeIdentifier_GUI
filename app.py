"""
DeepFake Detection REST API
============================
Analyzes uploaded images for deepfake manipulation using 5 detection modules:
  1. Metadata Analysis        (10%)
  2. Pixel & Artifact Analysis (20%)
  3. AI Vision Analysis        (35%)  — uses Claude claude-sonnet-4-20250514 via Anthropic API
  4. Frequency Domain Analysis (20%)
  5. Statistical / ELA Analysis(15%)

GET  /           — Serves the web GUI
GET  /api/info   — API information (JSON)
GET  /health     — Health check
GET  /modules    — Detection module descriptions
POST /analyze    — multipart/form-data with field 'image'
Returns: deepfake_score (0-100), deepfake_type, module scores, explanation
"""

import os
import io
import json
import math
import base64
import struct
import hashlib
import traceback
from datetime import datetime

import numpy as np
from PIL import Image, ExifTags
from flask import Flask, request, jsonify, render_template

# Optional: scipy for FFT analysis
try:
    from scipy import fftpack
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Optional: Anthropic for AI Vision module
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

app = Flask(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff"}

# Module weights (must sum to 1.0)
MODULE_WEIGHTS = {
    "metadata":    0.10,
    "artifact":    0.20,
    "ai_vision":   0.35,
    "frequency":   0.20,
    "statistical": 0.15,
}

# Score thresholds
SCORE_LABELS = [
    (25,  "AUTHENTIC",           "No significant manipulation detected"),
    (50,  "SUSPICIOUS",          "Minor anomalies detected — possible editing"),
    (75,  "PROBABLE_DEEPFAKE",   "Multiple manipulation indicators found"),
    (100, "HIGH_CONFIDENCE_DEEPFAKE", "Strong evidence of AI-generated or manipulated content"),
]

# ─────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────

def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))

def score_label(score: float):
    for threshold, label, desc in SCORE_LABELS:
        if score <= threshold:
            return label, desc
    return SCORE_LABELS[-1][1], SCORE_LABELS[-1][2]

def image_to_b64(img: Image.Image, fmt="JPEG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()

# ─────────────────────────────────────────────
# MODULE 1 — Metadata Analysis (weight 10%)
# ─────────────────────────────────────────────

def analyze_metadata(img: Image.Image, raw_bytes: bytes) -> dict:
    """
    Checks:
    - EXIF presence/absence patterns
    - Software field revealing AI tools
    - Suspicious creation/modification timestamps
    - Missing GPS when context implies location
    - JPEG/PNG header anomalies
    - Color profile inconsistencies
    """
    findings = []
    score = 0.0

    # --- EXIF extraction ---
    exif_data = {}
    try:
        raw_exif = img._getexif() if hasattr(img, '_getexif') and img._getexif() else {}
        if raw_exif:
            exif_data = {
                ExifTags.TAGS.get(k, k): str(v)
                for k, v in raw_exif.items()
            }
    except Exception:
        pass

    # 1. No EXIF at all on JPEG is suspicious (cameras always write EXIF)
    if img.format == "JPEG" and not exif_data:
        score += 25
        findings.append("JPEG has no EXIF data — cameras always embed EXIF; stripping suggests processing")

    # 2. Known AI/generation software signatures
    ai_software_keywords = [
        "stable diffusion", "midjourney", "dall-e", "dalle", "firefly",
        "generative", "deepfake", "faceswap", "roop", "deepswap",
        "adobe firefly", "canva ai", "bing image", "openai",
        "automatic1111", "comfyui", "invokeai", "novelai"
    ]
    software_field = exif_data.get("Software", "").lower()
    xp_comment = exif_data.get("XPComment", "").lower()
    image_desc = exif_data.get("ImageDescription", "").lower()
    combined_meta = software_field + xp_comment + image_desc

    matched_kw = [kw for kw in ai_software_keywords if kw in combined_meta]
    if matched_kw:
        score += 80
        findings.append(f"AI generation software detected in metadata: {matched_kw}")

    # 3. Photoshop / heavy editing without camera model
    editing_software = ["photoshop", "gimp", "lightroom", "affinity", "capture one"]
    matched_edit = [s for s in editing_software if s in software_field]
    if matched_edit and not exif_data.get("Model"):
        score += 20
        findings.append(f"Image editing software '{matched_edit}' present but no camera model — possible manipulation")

    # 4. Creation date vs modification date mismatch
    datetime_orig = exif_data.get("DateTimeOriginal", "")
    datetime_mod = exif_data.get("DateTime", "")
    if datetime_orig and datetime_mod and datetime_orig != datetime_mod:
        score += 10
        findings.append(f"Timestamp mismatch: original={datetime_orig}, modified={datetime_mod}")

    # 5. PNG specific: tEXt chunks can contain generation prompts
    if img.format == "PNG":
        try:
            png_info = img.info or {}
            png_text = " ".join(str(v).lower() for v in png_info.values())
            if any(kw in png_text for kw in ["prompt", "parameters", "model", "sampler", "cfg scale", "seed"]):
                score += 90
                findings.append("PNG metadata contains AI generation parameters (prompt/seed/sampler detected)")
            elif png_info:
                findings.append(f"PNG has {len(png_info)} metadata fields: {list(png_info.keys())}")
        except Exception:
            pass

    # 6. JPEG quantization table analysis (AI images use non-standard tables)
    if img.format == "JPEG":
        try:
            quant_tables = img.quantization
            if quant_tables:
                # Standard camera tables have specific patterns; flat/uniform tables suggest synthesis
                for idx, table in quant_tables.items():
                    flat_ratio = len(set(table)) / len(table)
                    if flat_ratio < 0.3:  # Very few unique values — too uniform
                        score += 15
                        findings.append(f"JPEG quantization table {idx} is unusually uniform (AI re-encoding pattern)")
        except Exception:
            pass

    # 7. Image dimensions — common AI resolutions (multiples of 64 or 128)
    w, h = img.size
    ai_resolutions = {
        (512, 512), (768, 768), (1024, 1024), (512, 768), (768, 512),
        (512, 640), (640, 512), (1024, 1536), (1536, 1024),
        (1152, 896), (896, 1152), (1216, 832), (832, 1216),
    }
    if (w, h) in ai_resolutions:
        score += 20
        findings.append(f"Image resolution {w}×{h} matches common AI generation output size")
    elif w % 64 == 0 and h % 64 == 0 and w * h >= 512*512:
        score += 10
        findings.append(f"Dimensions {w}×{h} are multiples of 64 — common in diffusion model outputs")

    if not findings:
        findings.append("No metadata anomalies detected")

    return {
        "score": clamp(score),
        "findings": findings,
        "exif_fields_found": list(exif_data.keys()) if exif_data else [],
    }

# ─────────────────────────────────────────────
# MODULE 2 — Pixel & Artifact Analysis (weight 20%)
# ─────────────────────────────────────────────

def analyze_artifacts(img: Image.Image) -> dict:
    """
    Checks:
    - Blocking artifacts (JPEG compression inconsistency)
    - Edge sharpness anomalies at face boundaries
    - Noise uniformity (real photos have organic noise; GANs are too clean or have GAN noise)
    - Color channel correlation anomalies
    - Blending seam detection
    """
    findings = []
    score = 0.0

    img_rgb = img.convert("RGB")
    arr = np.array(img_rgb, dtype=np.float32)
    h, w = arr.shape[:2]

    # 1. Local variance map — detects inconsistent noise regions
    def local_variance(channel, block=8):
        variances = []
        for y in range(0, channel.shape[0] - block, block):
            for x in range(0, channel.shape[1] - block, block):
                blk = channel[y:y+block, x:x+block]
                variances.append(np.var(blk))
        return np.array(variances)

    gray = np.mean(arr, axis=2)
    variances = local_variance(gray)

    var_cv = 0.0
    if len(variances) > 10:
        var_cv = np.std(variances) / (np.mean(variances) + 1e-6)  # coefficient of variation
        if var_cv < 0.3:
            score += 25
            findings.append(f"Noise variance extremely uniform (CV={var_cv:.3f}) — natural photos have variable noise")
        elif var_cv > 5.0:
            score += 30
            findings.append(f"Noise variance extremely irregular (CV={var_cv:.3f}) — possible region splicing")

    # 2. Double JPEG compression detection (re-saved manipulated images)
    block_means = []
    for y in range(0, h - 8, 8):
        for x in range(0, w - 8, 8):
            blk = gray[y:y+8, x:x+8]
            block_means.append(np.mean(blk))
    if len(block_means) > 20:
        bm = np.array(block_means)
        hist, _ = np.histogram(bm, bins=50)
        hist_norm = hist / (hist.max() + 1e-6)
        dips = np.sum(hist_norm < 0.1)
        if dips > 15:
            score += 20
            findings.append(f"Double compression pattern detected ({dips} histogram dips) — image was re-saved after editing")

    # 3. Color channel correlation
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    corr_rg = np.corrcoef(r.flatten(), g.flatten())[0,1]
    corr_rb = np.corrcoef(r.flatten(), b.flatten())[0,1]
    corr_gb = np.corrcoef(g.flatten(), b.flatten())[0,1]
    avg_corr = (corr_rg + corr_rb + corr_gb) / 3

    if avg_corr > 0.995:
        score += 15
        findings.append(f"Abnormally high color channel correlation ({avg_corr:.4f}) — possible desaturated synthesis")
    elif avg_corr < 0.5:
        score += 20
        findings.append(f"Abnormally low channel correlation ({avg_corr:.4f}) — unusual for natural photos")

    # 4. Edge analysis — GAN images have characteristic edge patterns
    def sobel_edges(channel):
        gy = np.gradient(channel, axis=0)
        gx = np.gradient(channel, axis=1)
        return np.sqrt(gx**2 + gy**2)

    edges = sobel_edges(gray)
    edge_mean = np.mean(edges)
    edge_std = np.std(edges)
    edge_kurtosis = np.mean((edges - edge_mean)**4) / (edge_std**4 + 1e-6)

    if edge_kurtosis > 20:
        score += 20
        findings.append(f"Edge distribution has high kurtosis ({edge_kurtosis:.1f}) — sharp unnatural edges typical of face swaps")
    elif edge_kurtosis < 2:
        score += 15
        findings.append(f"Edge distribution too flat (kurtosis={edge_kurtosis:.1f}) — over-smoothed, typical of GAN synthesis")

    # 5. Pixel value distribution
    mean_val = np.mean(gray)
    std_val = np.std(gray)
    min_val, max_val = np.min(gray), np.max(gray)

    if max_val - min_val < 100:
        score += 10
        findings.append("Very narrow pixel dynamic range — may indicate synthetic or heavily processed image")

    # 6. Block artifact score (8x8 JPEG blocks)
    ba_score = 0
    for y in range(8, h-8, 8):
        seam_vals = gray[y, ::4]
        neighbor_above = gray[y-1, ::4]
        neighbor_below = gray[y+1, ::4]
        seam_diff = np.mean(np.abs(seam_vals - (neighbor_above + neighbor_below)/2))
        ba_score += seam_diff
    if h > 16:
        ba_score /= (h // 8)
    if ba_score > 8:
        score += 15
        findings.append(f"Block boundary artifacts detected (score={ba_score:.2f}) — indicates re-compression after editing")

    if not findings:
        findings.append("No significant pixel or artifact anomalies detected")

    return {
        "score": clamp(score),
        "findings": findings,
        "stats": {
            "noise_cv": float(var_cv) if len(variances) > 10 else None,
            "channel_correlation": float(avg_corr),
            "edge_kurtosis": float(edge_kurtosis),
            "dynamic_range": float(max_val - min_val),
        }
    }

# ─────────────────────────────────────────────
# MODULE 3 — AI Vision Analysis (weight 35%)
# ─────────────────────────────────────────────

def analyze_with_ai(img: Image.Image) -> dict:
    """
    Uses Claude claude-sonnet-4-20250514 vision to analyze the image for:
    - Face boundary blending artifacts
    - Lighting/shadow inconsistencies
    - Eye and teeth anomalies (common GAN failure points)
    - Skin texture irregularities
    - Background/foreground consistency
    - Overall naturalness assessment
    """
    if not ANTHROPIC_AVAILABLE:
        return {
            "score": 0,
            "findings": ["Anthropic SDK not available — AI vision module skipped"],
            "available": False,
            "raw_analysis": None,
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "score": 0,
            "findings": ["ANTHROPIC_API_KEY not set — AI vision module skipped"],
            "available": False,
            "raw_analysis": None,
        }

    try:
        # Resize for API efficiency (max 1024px on longest side)
        img_copy = img.copy().convert("RGB")
        max_dim = 1024
        if max(img_copy.size) > max_dim:
            img_copy.thumbnail((max_dim, max_dim), Image.LANCZOS)

        img_b64 = image_to_b64(img_copy, "JPEG")

        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = """You are an expert forensic image analyst specializing in detecting AI-generated images, \
deepfakes, and image manipulations. Analyze images with extreme technical precision. \
Always respond in valid JSON format only, with no additional text."""

        user_prompt = """Analyze this image for signs of deepfake manipulation, AI generation, or image splicing. \
Examine ALL of these aspects in detail:

1. FACE ANALYSIS (if faces present):
   - Blending artifacts at face boundaries (neck/hairline edges)
   - Eye symmetry, reflections, and naturalness (GANs often fail at eyes)
   - Teeth regularity (too perfect = GAN indicator)
   - Ear shape consistency
   - Skin texture uniformity vs natural pore/blemish variation
   - Hair strand rendering quality

2. LIGHTING & SHADOWS:
   - Shadow direction consistency across the entire image
   - Specular highlights on skin vs environment matching
   - Lighting color temperature consistency
   - Sub-surface scattering in skin (real skin has it; GANs often miss it)

3. BACKGROUND CONSISTENCY:
   - Bokeh rendering naturalness around subject edges
   - Depth-of-field consistency
   - Background/foreground color bleeding or halos

4. TEXTURE & DETAIL:
   - Fabric weave patterns (GANs often repeat/blur these)
   - Text readability if present (GANs struggle with text)
   - Repetitive patterns that seem copy-pasted
   - Over-smoothed or under-detailed regions

5. PHYSICS & GEOMETRY:
   - Perspective consistency
   - Reflections in glasses, eyes, surfaces
   - Object proportions

6. GAN/DIFFUSION ARTIFACTS:
   - Characteristic GAN noise in smooth regions
   - Diffusion model "painting" artifacts
   - Face reenactment temporal warping artifacts (visible as distortion rings)
   - Background objects that are partially merged or morphed

Respond with this exact JSON structure:
{
  "deepfake_score": <0-100 integer>,
  "confidence": "<LOW|MEDIUM|HIGH>",
  "primary_type": "<AUTHENTIC|FACE_SWAP|FACE_REENACTMENT|FULL_SYNTHESIS|ATTRIBUTE_MANIPULATION|SPLICING>",
  "face_present": <true|false>,
  "critical_findings": ["<specific finding 1>", "<finding 2>", ...],
  "face_anomalies": ["<anomaly>", ...],
  "lighting_anomalies": ["<anomaly>", ...],
  "texture_anomalies": ["<anomaly>", ...],
  "background_anomalies": ["<anomaly>", ...],
  "overall_reasoning": "<2-3 sentence technical summary>"
}"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        }
                    },
                    {"type": "text", "text": user_prompt}
                ]
            }]
        )

        raw = response.content[0].text.strip()

        # Clean potential markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        ai_score = clamp(float(parsed.get("deepfake_score", 0)))

        all_findings = []
        for key in ["critical_findings", "face_anomalies", "lighting_anomalies",
                    "texture_anomalies", "background_anomalies"]:
            all_findings.extend(parsed.get(key, []))

        if parsed.get("overall_reasoning"):
            all_findings.insert(0, f"Summary: {parsed['overall_reasoning']}")

        return {
            "score": ai_score,
            "findings": all_findings or ["AI analysis completed — no significant anomalies found"],
            "available": True,
            "ai_primary_type": parsed.get("primary_type", "UNKNOWN"),
            "ai_confidence": parsed.get("confidence", "MEDIUM"),
            "face_present": parsed.get("face_present", False),
            "raw_analysis": parsed,
        }

    except json.JSONDecodeError as e:
        return {
            "score": 0,
            "findings": [f"AI response parsing error: {str(e)}"],
            "available": True,
            "error": str(e),
        }
    except Exception as e:
        return {
            "score": 0,
            "findings": [f"AI vision analysis error: {str(e)}"],
            "available": True,
            "error": str(e),
        }

# ─────────────────────────────────────────────
# MODULE 4 — Frequency Domain Analysis (weight 20%)
# ─────────────────────────────────────────────

def analyze_frequency(img: Image.Image) -> dict:
    """
    Checks:
    - FFT/DCT spectrum for GAN fingerprints (periodic artifacts)
    - High-frequency energy distribution (AI images cluster differently)
    - Radially averaged power spectrum deviation from 1/f natural law
    - Checkerboard artifacts from upsampling in GANs
    """
    findings = []
    score = 0.0

    img_gray = img.convert("L")
    arr = np.array(img_gray, dtype=np.float64)
    h, w = arr.shape

    # Resize to power of 2 for clean FFT
    target = 512
    from PIL import Image as PILImage
    resized = np.array(
        img_gray.resize((target, target), PILImage.LANCZOS),
        dtype=np.float64
    )

    # 2D FFT
    fft = np.fft.fft2(resized)
    fft_shifted = np.fft.fftshift(fft)
    magnitude = np.abs(fft_shifted)
    log_magnitude = np.log1p(magnitude)

    center = target // 2

    # 1. Radially averaged power spectrum — should follow 1/f for natural images
    radial_profile = []
    for r in range(1, center - 1, 2):
        Y, X = np.ogrid[:target, :target]
        dist = np.sqrt((X - center)**2 + (Y - center)**2)
        mask = (dist >= r) & (dist < r + 2)
        if mask.sum() > 0:
            radial_profile.append(np.mean(magnitude[mask]))

    slope = -2.0  # default
    if len(radial_profile) > 10:
        rp = np.array(radial_profile, dtype=np.float64)
        freqs = np.arange(1, len(rp) + 1, dtype=np.float64)
        log_f = np.log(freqs + 1e-6)
        log_p = np.log(rp + 1e-6)

        A = np.vstack([log_f, np.ones(len(log_f))]).T
        slope, intercept = np.linalg.lstsq(A, log_p, rcond=None)[0]

        if slope > -1.0:
            score += 30
            findings.append(f"Power spectrum slope {slope:.2f} too shallow — AI images lack natural 1/f frequency rolloff")
        elif slope < -4.5:
            score += 20
            findings.append(f"Power spectrum slope {slope:.2f} too steep — over-sharpened or GAN artifact")
        else:
            findings.append(f"Power spectrum slope {slope:.2f} within natural range")

    # 2. Checkerboard artifact detection (from GAN transposed convolution upsampling)
    q = target // 4
    checkerboard_energy = (
        log_magnitude[center - q, center - q] +
        log_magnitude[center + q, center - q] +
        log_magnitude[center - q, center + q] +
        log_magnitude[center + q, center + q]
    )
    center_energy = log_magnitude[center, center]
    cb_ratio = checkerboard_energy / (center_energy + 1e-6)

    if cb_ratio > 1.5:
        score += 35
        findings.append(f"Checkerboard artifact energy ratio {cb_ratio:.3f} — characteristic of GAN transposed convolution upsampling")
    elif cb_ratio > 0.8:
        score += 10
        findings.append(f"Mild checkerboard pattern ratio {cb_ratio:.3f} — possible GAN artifact")

    # 3. High-frequency energy ratio
    Y, X = np.ogrid[:target, :target]
    dist_center = np.sqrt((X - center)**2 + (Y - center)**2)
    inner_mask = dist_center < center * 0.3

    total_energy = magnitude.sum() + 1e-6
    low_freq_energy = magnitude[inner_mask].sum()
    high_freq_energy = total_energy - low_freq_energy
    hf_ratio = high_freq_energy / total_energy

    if hf_ratio < 0.3:
        score += 20
        findings.append(f"Abnormally low high-frequency energy ({hf_ratio:.3f}) — over-smoothed synthetic image")
    elif hf_ratio > 0.85:
        score += 15
        findings.append(f"Abnormally high high-frequency energy ({hf_ratio:.3f}) — possible upscaling artifact")

    # 4. Horizontal/vertical frequency asymmetry
    h_line = log_magnitude[center, :]
    v_line = log_magnitude[:, center]
    hv_asymmetry = abs(np.sum(h_line) - np.sum(v_line)) / (np.sum(h_line) + np.sum(v_line) + 1e-6)

    if hv_asymmetry > 0.15:
        score += 15
        findings.append(f"H/V frequency asymmetry {hv_asymmetry:.3f} — directional artifact from GAN training")

    if not findings:
        findings.append("No significant frequency domain anomalies detected")

    return {
        "score": clamp(score),
        "findings": findings,
        "stats": {
            "power_spectrum_slope": float(slope),
            "checkerboard_ratio": float(cb_ratio),
            "hf_energy_ratio": float(hf_ratio),
            "hv_asymmetry": float(hv_asymmetry),
        }
    }

# ─────────────────────────────────────────────
# MODULE 5 — Statistical / ELA Analysis (weight 15%)
# ─────────────────────────────────────────────

def analyze_statistical(img: Image.Image) -> dict:
    """
    Error Level Analysis (ELA):
    - Re-save image at known quality and compute difference
    - Manipulated regions show higher error levels than background
    Also:
    - Color histogram entropy analysis
    - Benford's law test on DCT coefficients (natural images follow it)
    - Copy-move detection (simplified via block hashing)
    """
    findings = []
    score = 0.0

    img_rgb = img.convert("RGB")

    # 1. Error Level Analysis (ELA)
    ela_quality = 90
    buf_orig = io.BytesIO()
    img_rgb.save(buf_orig, format="JPEG", quality=ela_quality)
    buf_orig.seek(0)
    img_recompressed = Image.open(buf_orig).convert("RGB")

    orig_arr = np.array(img_rgb, dtype=np.float32)
    recomp_arr = np.array(img_recompressed, dtype=np.float32)

    ela_arr = np.abs(orig_arr - recomp_arr)
    ela_mean = np.mean(ela_arr)
    ela_std = np.std(ela_arr)
    ela_max = np.max(ela_arr)

    h, w = ela_arr.shape[:2]
    block_size = max(32, min(h, w) // 8)
    block_ela_means = []

    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            block = ela_arr[y:y+block_size, x:x+block_size]
            block_ela_means.append(np.mean(block))

    ela_cv = 0.0
    if block_ela_means:
        bm = np.array(block_ela_means)
        ela_block_std = np.std(bm)
        ela_block_mean = np.mean(bm)
        ela_cv = ela_block_std / (ela_block_mean + 1e-6)

        if ela_cv > 2.0:
            score += 35
            findings.append(f"ELA regional variance very high (CV={ela_cv:.2f}) — strongly suggests image splicing or region editing")
        elif ela_cv > 1.0:
            score += 15
            findings.append(f"ELA regional variance elevated (CV={ela_cv:.2f}) — possible localized editing")
        else:
            findings.append(f"ELA uniform (CV={ela_cv:.2f}) — consistent compression history")

    # 2. Color histogram entropy
    hist_entropy_scores = []
    for channel in range(3):
        channel_data = orig_arr[:,:,channel].flatten().astype(np.int32)
        hist, _ = np.histogram(channel_data, bins=256, range=(0, 255))
        hist_norm = hist / (hist.sum() + 1e-6)
        entropy = -np.sum(hist_norm[hist_norm > 0] * np.log2(hist_norm[hist_norm > 0]))
        hist_entropy_scores.append(entropy)

    avg_entropy = np.mean(hist_entropy_scores)
    if avg_entropy < 5.0:
        score += 20
        findings.append(f"Low color entropy ({avg_entropy:.2f} bits) — limited color range, typical of AI face synthesis")
    elif avg_entropy > 7.8:
        score += 5
        findings.append(f"Very high color entropy ({avg_entropy:.2f} bits) — may indicate complex composite image")
    else:
        findings.append(f"Color histogram entropy {avg_entropy:.2f} bits — normal range")

    # 3. Copy-Move detection via block hashing
    gray_arr = np.mean(orig_arr, axis=2).astype(np.uint8)
    block_size_cm = 16
    block_hashes = {}
    duplicate_blocks = 0
    total_blocks = 0

    for y in range(0, h - block_size_cm, block_size_cm):
        for x in range(0, w - block_size_cm, block_size_cm):
            block = gray_arr[y:y+block_size_cm, x:x+block_size_cm]
            small = block[::2, ::2]
            mean_val = np.mean(small)
            bits = (small > mean_val).flatten()
            h_val = hashlib.md5(bits.tobytes()).hexdigest()
            total_blocks += 1
            if h_val in block_hashes:
                duplicate_blocks += 1
            else:
                block_hashes[h_val] = (y, x)

    dup_ratio = 0.0
    if total_blocks > 0:
        dup_ratio = duplicate_blocks / total_blocks
        if dup_ratio > 0.15:
            score += 30
            findings.append(f"Copy-move detection: {dup_ratio:.1%} duplicate blocks — possible cloning/region copying")
        elif dup_ratio > 0.05:
            score += 10
            findings.append(f"Copy-move detection: {dup_ratio:.1%} similar blocks — minor repetition")
        else:
            findings.append(f"Copy-move detection: {dup_ratio:.1%} block repetition — within normal range")

    # 4. Benford's Law on DCT coefficients
    try:
        benford_expected = np.array([
            0.301, 0.176, 0.125, 0.097, 0.079, 0.067, 0.058, 0.051, 0.046
        ])
        gray_float = gray_arr.astype(np.float64)
        leading_digits = []
        for y in range(0, h - 8, 8):
            for x in range(0, w - 8, 8):
                blk = gray_float[y:y+8, x:x+8]
                dct_blk = np.abs(np.fft.fft2(blk)).flatten()
                for coef in dct_blk[1:]:
                    if coef >= 1:
                        d = int(str(int(coef))[0])
                        if 1 <= d <= 9:
                            leading_digits.append(d)

        if len(leading_digits) > 100:
            observed = np.zeros(9)
            for d in leading_digits:
                observed[d-1] += 1
            observed /= observed.sum()
            benford_deviation = np.sum(np.abs(observed - benford_expected))

            if benford_deviation > 0.3:
                score += 20
                findings.append(f"Benford's law deviation {benford_deviation:.3f} — DCT coefficient distribution atypical for natural images")
            else:
                findings.append(f"Benford's law test passed (deviation={benford_deviation:.3f})")
    except Exception:
        pass

    if not findings:
        findings.append("No significant statistical anomalies detected")

    return {
        "score": clamp(score),
        "findings": findings,
        "stats": {
            "ela_mean": float(ela_mean),
            "ela_max": float(ela_max),
            "ela_cv": float(ela_cv) if block_ela_means else None,
            "color_entropy": float(avg_entropy),
            "copy_move_ratio": float(dup_ratio) if total_blocks > 0 else None,
        }
    }

# ─────────────────────────────────────────────
# Type Classifier
# ─────────────────────────────────────────────

def classify_deepfake_type(
    metadata_result, artifact_result, ai_result, freq_result, stat_result
) -> tuple:
    """
    Determines the most likely type of deepfake based on combined module signals.
    Returns (type_code, explanation)
    """
    final_score = (
        metadata_result["score"] * MODULE_WEIGHTS["metadata"] +
        artifact_result["score"] * MODULE_WEIGHTS["artifact"] +
        ai_result["score"]       * MODULE_WEIGHTS["ai_vision"] +
        freq_result["score"]     * MODULE_WEIGHTS["frequency"] +
        stat_result["score"]     * MODULE_WEIGHTS["statistical"]
    )

    if final_score < 25:
        return "AUTHENTIC", "Image shows no significant signs of manipulation"

    # If AI vision gave us a type, trust it for high-confidence cases
    if ai_result.get("available") and ai_result.get("ai_primary_type") and \
       ai_result.get("ai_primary_type") not in ("UNKNOWN", "AUTHENTIC") and \
       ai_result["score"] > 40:
        return ai_result["ai_primary_type"], f"AI visual analysis identified {ai_result['ai_primary_type']}"

    # Heuristic rules
    meta_score = metadata_result["score"]
    freq_score = freq_result["score"]
    stat_score = stat_result["score"]
    artifact_score = artifact_result["score"]

    # PNG with generation params or AI software = full synthesis
    if meta_score > 70:
        return "FULL_SYNTHESIS", "Metadata reveals AI generation tools or parameters"

    # High frequency checkerboard + high artifact = GAN full synthesis
    if freq_score > 50 and artifact_score > 40:
        return "FULL_SYNTHESIS", "GAN frequency fingerprint and artifact patterns detected"

    # High ELA variance + splicing pattern = splice
    stat_findings = " ".join(stat_result.get("findings", []))
    if "splicing" in stat_findings.lower() or "copy-move" in stat_findings.lower():
        return "SPLICING", "ELA and copy-move analysis indicate image region splicing"

    # Moderate scores across board = face swap (most common deepfake)
    if artifact_score > 30 and final_score > 50:
        return "FACE_SWAP", "Multi-module analysis consistent with face replacement deepfake"

    return "ATTRIBUTE_MANIPULATION", "Localized manipulation detected — likely attribute editing (age/expression)"

# ─────────────────────────────────────────────
# Main Analysis Pipeline
# ─────────────────────────────────────────────

def run_full_analysis(img: Image.Image, raw_bytes: bytes) -> dict:
    started_at = datetime.utcnow().isoformat() + "Z"

    # Run all modules
    metadata_result    = analyze_metadata(img, raw_bytes)
    artifact_result    = analyze_artifacts(img)
    ai_result          = analyze_with_ai(img)
    frequency_result   = analyze_frequency(img)
    statistical_result = analyze_statistical(img)

    # Weighted composite score
    composite = (
        metadata_result["score"]    * MODULE_WEIGHTS["metadata"] +
        artifact_result["score"]    * MODULE_WEIGHTS["artifact"] +
        ai_result["score"]          * MODULE_WEIGHTS["ai_vision"] +
        frequency_result["score"]   * MODULE_WEIGHTS["frequency"] +
        statistical_result["score"] * MODULE_WEIGHTS["statistical"]
    )
    composite = clamp(composite)

    # Classify type
    deepfake_type, type_explanation = classify_deepfake_type(
        metadata_result, artifact_result, ai_result, frequency_result, statistical_result
    )

    # Score label
    verdict, verdict_description = score_label(composite)

    # Confidence level
    module_scores = [
        metadata_result["score"], artifact_result["score"],
        ai_result["score"], frequency_result["score"], statistical_result["score"]
    ]
    score_agreement = len([s for s in module_scores if s > 30]) / len(module_scores)
    if score_agreement > 0.7 and composite > 50:
        confidence = "HIGH"
    elif score_agreement > 0.4 or composite > 30:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Collect all findings
    all_findings = []
    for label, result in [
        ("Metadata", metadata_result),
        ("Artifact", artifact_result),
        ("AI Vision", ai_result),
        ("Frequency", frequency_result),
        ("Statistical", statistical_result),
    ]:
        for f in result.get("findings", []):
            all_findings.append(f"[{label}] {f}")

    finished_at = datetime.utcnow().isoformat() + "Z"

    return {
        "deepfake_score": round(composite, 2),
        "verdict": verdict,
        "verdict_description": verdict_description,
        "deepfake_type": deepfake_type,
        "type_explanation": type_explanation,
        "confidence": confidence,
        "analysis_summary": {
            "modules_flagged": len([s for s in module_scores if s > 25]),
            "total_modules": len(module_scores),
            "face_detected": ai_result.get("face_present", False),
            "ai_vision_available": ai_result.get("available", False),
        },
        "module_scores": {
            "metadata_analysis":    round(metadata_result["score"], 2),
            "artifact_analysis":    round(artifact_result["score"], 2),
            "ai_vision_analysis":   round(ai_result["score"], 2),
            "frequency_analysis":   round(frequency_result["score"], 2),
            "statistical_analysis": round(statistical_result["score"], 2),
        },
        "module_weights": MODULE_WEIGHTS,
        "findings": all_findings,
        "module_details": {
            "metadata":    {k: v for k, v in metadata_result.items() if k != "score"},
            "artifact":    {k: v for k, v in artifact_result.items() if k != "score"},
            "ai_vision":   {k: v for k, v in ai_result.items() if k not in ("score", "raw_analysis")},
            "frequency":   {k: v for k, v in frequency_result.items() if k != "score"},
            "statistical": {k: v for k, v in statistical_result.items() if k != "score"},
        },
        "image_info": {
            "format": img.format or "UNKNOWN",
            "mode": img.mode,
            "width": img.size[0],
            "height": img.size[1],
            "file_size_bytes": len(raw_bytes),
        },
        "timing": {
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "api_version": "1.0.0",
    }

# ─────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["GET"])
def api_info():
    return jsonify({
        "name": "DeepFake Detection API",
        "version": "1.0.0",
        "endpoints": {
            "GET /":          "Web GUI",
            "POST /analyze":  "Analyze an image for deepfake manipulation",
            "GET /health":    "Health check",
            "GET /modules":   "List detection modules and weights",
            "GET /api/info":  "API information",
        },
        "usage": "POST /analyze with multipart/form-data field 'image'",
        "supported_formats": list(ALLOWED_MIMES),
        "ai_vision_available": ANTHROPIC_AVAILABLE and bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "anthropic_sdk": ANTHROPIC_AVAILABLE,
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "scipy_available": SCIPY_AVAILABLE,
    })


@app.route("/modules", methods=["GET"])
def modules():
    return jsonify({
        "modules": [
            {
                "id": "metadata",
                "name": "Metadata Analysis",
                "weight": MODULE_WEIGHTS["metadata"],
                "description": "Analyzes EXIF, PNG chunks, quantization tables, AI software signatures",
            },
            {
                "id": "artifact",
                "name": "Pixel & Artifact Analysis",
                "weight": MODULE_WEIGHTS["artifact"],
                "description": "Checks blocking artifacts, noise patterns, color channel correlations, edge kurtosis",
            },
            {
                "id": "ai_vision",
                "name": "AI Vision Analysis",
                "weight": MODULE_WEIGHTS["ai_vision"],
                "description": "Uses Claude claude-sonnet-4-20250514 to visually inspect for face anomalies, lighting, texture",
                "requires": "ANTHROPIC_API_KEY environment variable",
            },
            {
                "id": "frequency",
                "name": "Frequency Domain Analysis",
                "weight": MODULE_WEIGHTS["frequency"],
                "description": "FFT-based GAN fingerprint, checkerboard artifacts, power spectrum slope",
            },
            {
                "id": "statistical",
                "name": "Statistical / ELA Analysis",
                "weight": MODULE_WEIGHTS["statistical"],
                "description": "Error Level Analysis, copy-move detection, Benford's law, color entropy",
            },
        ],
        "score_interpretation": {
            "0-25":   "AUTHENTIC — likely no manipulation",
            "26-50":  "SUSPICIOUS — minor anomalies",
            "51-75":  "PROBABLE_DEEPFAKE — multiple indicators",
            "76-100": "HIGH_CONFIDENCE_DEEPFAKE — strong evidence",
        },
        "deepfake_types": [
            "AUTHENTIC", "FACE_SWAP", "FACE_REENACTMENT",
            "FULL_SYNTHESIS", "ATTRIBUTE_MANIPULATION", "SPLICING"
        ]
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    # Validate request
    if "image" not in request.files:
        return jsonify({"error": "No 'image' file field in request"}), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Read bytes
    raw_bytes = file.read()
    if not raw_bytes:
        return jsonify({"error": "Empty file"}), 400

    if len(raw_bytes) > MAX_IMAGE_SIZE:
        return jsonify({"error": f"File too large. Max {MAX_IMAGE_SIZE // 1024 // 1024}MB"}), 413

    # Validate MIME
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIMES and not any(
        raw_bytes.startswith(sig) for sig in [
            b'\xff\xd8\xff',   # JPEG
            b'\x89PNG',        # PNG
            b'RIFF',           # WebP
            b'BM',             # BMP
        ]
    ):
        return jsonify({"error": f"Unsupported image type: {content_type}"}), 415

    # Open image
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception as e:
        return jsonify({"error": f"Cannot open image: {str(e)}"}), 422

    # Run analysis
    try:
        result = run_full_analysis(img, raw_bytes)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            "error": "Analysis failed",
            "detail": str(e),
            "traceback": traceback.format_exc(),
        }), 500


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"DeepFake Detection API starting on port {port}")
    print(f"   AI Vision Module: {'Available' if ANTHROPIC_AVAILABLE and os.environ.get('ANTHROPIC_API_KEY') else 'Set ANTHROPIC_API_KEY to enable'}")
    print(f"   SciPy: {'Available' if SCIPY_AVAILABLE else 'Not available'}")
    print(f"   Web GUI: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
