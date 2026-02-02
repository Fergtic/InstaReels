"""Content analyzer using OpenAI API with vision and Whisper for transcription."""

import base64
import json
import re
import tempfile
from pathlib import Path
from typing import Optional
import logging

import cv2
from PIL import Image
from openai import OpenAI

logger = logging.getLogger(__name__)

# Try to import whisper, but make it optional
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("Whisper not available. Audio transcription will be skipped.")


class ContentAnalyzer:
    def __init__(self, openai_api_key: str):
        self.client = OpenAI(api_key=openai_api_key)
        self.whisper_model = None

        if WHISPER_AVAILABLE:
            try:
                logger.info("Loading Whisper model (base)...")
                self.whisper_model = whisper.load_model("base")
                logger.info("Whisper model loaded")
            except Exception as e:
                logger.warning(f"Failed to load Whisper model: {e}")

    def extract_frames(
        self,
        video_path: Path,
        num_frames: int = 4
    ) -> list[bytes]:
        """Extract frames from a video file as base64-encoded images."""
        frames = []

        try:
            cap = cv2.VideoCapture(str(video_path))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if total_frames == 0:
                logger.warning(f"No frames in video: {video_path}")
                return frames

            # Calculate frame positions (first, evenly spaced middle frames, last)
            if num_frames >= total_frames:
                positions = list(range(total_frames))
            else:
                positions = [
                    int(i * (total_frames - 1) / (num_frames - 1))
                    for i in range(num_frames)
                ]

            for pos in positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()

                if ret:
                    # Convert BGR to RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    # Resize if too large (max 1024 on longest side)
                    h, w = frame_rgb.shape[:2]
                    max_dim = 1024
                    if max(h, w) > max_dim:
                        scale = max_dim / max(h, w)
                        new_w, new_h = int(w * scale), int(h * scale)
                        frame_rgb = cv2.resize(frame_rgb, (new_w, new_h))

                    # Convert to PIL Image and then to bytes
                    pil_image = Image.fromarray(frame_rgb)

                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
                        pil_image.save(tmp.name, "JPEG", quality=85)
                        with open(tmp.name, "rb") as f:
                            frame_bytes = f.read()
                            frames.append(frame_bytes)

            cap.release()
            logger.info(f"Extracted {len(frames)} frames from video")

        except Exception as e:
            logger.error(f"Error extracting frames: {e}")

        return frames

    def transcribe_audio(self, video_path: Path) -> str:
        """Transcribe audio from a video file using Whisper."""
        if not WHISPER_AVAILABLE or not self.whisper_model:
            return ""

        try:
            # Extract audio and transcribe
            result = self.whisper_model.transcribe(
                str(video_path),
                language="en",
                fp16=False  # Use float32 for CPU compatibility
            )
            transcript = result.get("text", "").strip()
            logger.info(f"Transcribed audio: {transcript[:100]}...")
            return transcript
        except Exception as e:
            logger.warning(f"Error transcribing audio: {e}")
            return ""

    def analyze_reel(
        self,
        video_path: Path,
        caption: str = "",
        username: str = ""
    ) -> dict:
        """
        Analyze a reel using OpenAI GPT-4 Vision.

        Returns:
            dict with keys: humor_score, humor_category, explanation, suggested_comment
        """
        result = {
            "humor_score": 0,
            "humor_category": "unknown",
            "explanation": "",
            "suggested_comment": "",
            "transcript": ""
        }

        try:
            # Extract frames
            frames = self.extract_frames(video_path)
            if not frames:
                logger.warning("No frames extracted, cannot analyze")
                return result

            # Transcribe audio
            transcript = self.transcribe_audio(video_path)
            result["transcript"] = transcript

            # Build the message content
            content = []

            # Add frames as images
            for i, frame_bytes in enumerate(frames):
                frame_b64 = base64.standard_b64encode(frame_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{frame_b64}",
                        "detail": "low"  # Use low detail to reduce costs
                    }
                })

            # Build analysis prompt
            prompt_parts = [
                "You are analyzing an Instagram Reel/meme for humor.",
                f"\nCaption: {caption}" if caption else "",
                f"\nCreator: @{username}" if username else "",
                f"\nAudio transcript: {transcript}" if transcript else "\n(No audio/transcript available)",
                "\n\nBased on the frames shown and any available context, please analyze this content:",
                "\n\n1. HUMOR_SCORE: Rate the humor on a scale of 1-10 (1=not funny, 10=hilarious)",
                "\n2. HUMOR_CATEGORY: Classify the type of humor (choose one: relatable, absurd, wholesome, cringe, dark_humor, wordplay, physical_comedy, parody, observational, surreal, wholesome, cute_animals, gaming, other)",
                "\n3. EXPLANATION: Briefly explain what makes it funny (or not) in 1-2 sentences",
                "\n4. SUGGESTED_COMMENT: If you would comment on this, what would you say? Keep it under 15 words, casual tone, use emojis sparingly. If not worth commenting, say 'SKIP'",
                "\n\nRespond in this exact JSON format:",
                '\n{"humor_score": X, "humor_category": "category", "explanation": "...", "suggested_comment": "..."}'
            ]

            content.append({
                "type": "text",
                "text": "".join(prompt_parts)
            })

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": content}
                ]
            )

            # Parse response
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"OpenAI response: {response_text}")

            # Extract JSON from response (handle potential markdown code blocks)
            json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                result["humor_score"] = float(parsed.get("humor_score", 0))
                result["humor_category"] = parsed.get("humor_category", "unknown")
                result["explanation"] = parsed.get("explanation", "")
                result["suggested_comment"] = parsed.get("suggested_comment", "")

                if result["suggested_comment"].upper() == "SKIP":
                    result["suggested_comment"] = ""

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
        except Exception as e:
            logger.error(f"Error analyzing reel: {e}")

        return result

    def generate_comment(
        self,
        humor_category: str,
        explanation: str,
        caption: str = ""
    ) -> str:
        """Generate a fresh comment if the suggested one isn't suitable."""
        try:
            prompt = f"""Generate a brief, authentic-sounding Instagram comment for a Reel.

Context:
- Humor category: {humor_category}
- What made it funny: {explanation}
- Original caption: {caption if caption else 'N/A'}

Requirements:
- Under 15 words
- Casual, authentic tone (like a real person would comment)
- Use 0-2 emojis maximum
- Don't be cringe or overly enthusiastic
- Match the vibe of the content

Just respond with the comment text, nothing else."""

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=100,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            comment = response.choices[0].message.content.strip()
            # Remove quotes if present
            comment = comment.strip('"\'')
            return comment

        except Exception as e:
            logger.error(f"Error generating comment: {e}")
            return ""
