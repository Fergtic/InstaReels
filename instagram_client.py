"""Instagram client wrapper using instagrapi."""

import json
import time
import random
from pathlib import Path
from typing import Optional, Generator
import logging

from instagrapi import Client
from instagrapi.types import Media
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    RateLimitError,
    ClientError
)

logger = logging.getLogger(__name__)


class InstagramClient:
    def __init__(
        self,
        username: str,
        password: str,
        session_file: str = "instagram_session.json"
    ):
        self.username = username
        self.password = password
        self.session_file = Path(session_file)
        self.client = Client()
        self.logged_in = False

        # Configure client settings for safety
        self.client.delay_range = [1, 3]

    def login(self) -> bool:
        """Login to Instagram with session persistence."""
        try:
            # Try to load existing session
            if self.session_file.exists():
                logger.info("Loading existing session...")
                try:
                    self.client.load_settings(self.session_file)
                    self.client.login(self.username, self.password)
                    # Verify session is valid
                    self.client.get_timeline_feed()
                    self.logged_in = True
                    logger.info("Session restored successfully")
                    return True
                except Exception as e:
                    logger.warning(f"Session invalid, will re-login: {e}")
                    self.session_file.unlink(missing_ok=True)

            # Fresh login
            logger.info("Performing fresh login...")
            self.client.login(self.username, self.password)

            # Save session for future use
            self.client.dump_settings(self.session_file)
            self.logged_in = True
            logger.info("Login successful, session saved")
            return True

        except ChallengeRequired as e:
            logger.error(f"Challenge required (2FA or verification): {e}")
            logger.error("Please complete the challenge manually and try again")
            return False
        except RateLimitError as e:
            logger.error(f"Rate limited by Instagram: {e}")
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def _ensure_logged_in(self):
        """Ensure we're logged in before making requests."""
        if not self.logged_in:
            raise LoginRequired("Not logged in. Call login() first.")

    def get_reels_feed(self, max_reels: int = 50) -> Generator[dict, None, None]:
        """
        Fetch Reels from explore feed using raw API access.

        Yields dict with reel data instead of Media objects due to pydantic validation issues.
        """
        self._ensure_logged_in()

        count = 0
        seen_pks = set()
        max_id = ""

        while count < max_reels:
            try:
                logger.info(f"Fetching reels batch (count: {count})...")

                # Direct API call to clips/discover endpoint
                result = self.client.private_request(
                    "clips/discover/",
                    params={"max_id": max_id} if max_id else {},
                    data={
                        "is_scroll": "false" if not max_id else "true",
                        "is_clips_top_of_feed": "false"
                    }
                )

                items = result.get("items", [])
                if not items:
                    logger.info("No more reels available")
                    break

                for item in items:
                    if count >= max_reels:
                        break

                    media = item.get("media", {})
                    pk = media.get("pk")

                    if pk and pk not in seen_pks:
                        seen_pks.add(pk)

                        # Build a simplified reel dict with what we need
                        reel_data = {
                            "pk": pk,
                            "id": media.get("id"),
                            "code": media.get("code"),
                            "media_type": media.get("media_type"),
                            "caption_text": media.get("caption", {}).get("text", "") if media.get("caption") else "",
                            "user": media.get("user", {}),
                            "video_url": None,
                            "thumbnail_url": None
                        }

                        # Get video URL
                        video_versions = media.get("video_versions", [])
                        if video_versions:
                            reel_data["video_url"] = video_versions[0].get("url")

                        # Get thumbnail
                        image_versions = media.get("image_versions2", {}).get("candidates", [])
                        if image_versions:
                            reel_data["thumbnail_url"] = image_versions[0].get("url")

                        yield reel_data
                        count += 1

                # Get next page
                max_id = result.get("max_id") or result.get("paging_info", {}).get("max_id")
                if not max_id:
                    break

                # Small delay between batches
                time.sleep(1)

            except Exception as e:
                logger.error(f"Error fetching reels: {e}")
                break

        logger.info(f"Total reels fetched: {count}")

    def download_reel(self, reel_data: dict, output_dir: str = "temp_reels") -> Optional[Path]:
        """Download a reel video to a temporary location."""
        self._ensure_logged_in()

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        pk = reel_data.get("pk")
        video_url = reel_data.get("video_url")

        # If we have a direct video URL, download it
        if video_url:
            try:
                import requests
                response = requests.get(video_url, stream=True, timeout=30)
                response.raise_for_status()

                file_path = output_path / f"{pk}.mp4"
                with open(file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"Downloaded reel to: {file_path}")
                return file_path

            except Exception as e:
                logger.warning(f"Direct download failed: {e}, trying API method...")

        # Fallback to API download
        try:
            video_path = self.client.clip_download(pk, folder=output_path)
            logger.info(f"Downloaded reel to: {video_path}")
            return Path(video_path)
        except Exception as e:
            logger.error(f"Error downloading reel {pk}: {e}")
            return None

    def like_media(self, media_id: str) -> bool:
        """Like a media post using raw API."""
        self._ensure_logged_in()

        try:
            # Use raw API call to avoid pydantic validation issues
            result = self.client.private_request(
                f"media/{media_id}/like/",
                data={
                    "media_id": media_id,
                    "_uid": self.client.user_id,
                    "_uuid": self.client.uuid,
                }
            )
            logger.info(f"Liked media: {media_id}")
            return result.get("status") == "ok"
        except RateLimitError:
            logger.error("Rate limited while liking")
            raise
        except Exception as e:
            logger.error(f"Error liking media {media_id}: {e}")
            return False

    def comment_media(self, media_id: str, comment_text: str) -> bool:
        """Comment on a media post using raw API."""
        self._ensure_logged_in()

        try:
            # Use raw API call to avoid pydantic validation issues
            result = self.client.private_request(
                f"media/{media_id}/comment/",
                data={
                    "media_id": media_id,
                    "comment_text": comment_text,
                    "_uid": self.client.user_id,
                    "_uuid": self.client.uuid,
                }
            )
            logger.info(f"Commented on media {media_id}: {comment_text}")
            return result.get("status") == "ok"
        except RateLimitError:
            logger.error("Rate limited while commenting")
            raise
        except Exception as e:
            logger.error(f"Error commenting on media {media_id}: {e}")
            return False

    def share_media_to_user(self, media_id: str, username: str, reel_code: str = None) -> bool:
        """Share a media post to a user via direct message using raw API."""
        self._ensure_logged_in()

        try:
            # Get user ID from username
            try:
                user_info = self.client.private_request(
                    "users/web_profile_info/",
                    params={"username": username}
                )
                user_id = user_info.get("data", {}).get("user", {}).get("id")
            except Exception:
                # Fallback to library method
                user_id = self.client.user_id_from_username(username)

            if not user_id:
                logger.error(f"Could not find user ID for {username}")
                return False

            # Try multiple endpoints for sharing
            endpoints_to_try = [
                # Reel share endpoint
                {
                    "endpoint": "direct_v2/threads/broadcast/reel_share/",
                    "data": {
                        "media_id": str(media_id),
                        "recipient_users": f"[[{user_id}]]",
                        "client_context": self.client.generate_uuid(),
                        "_uid": str(self.client.user_id),
                        "_uuid": self.client.uuid,
                        "text": "",
                    }
                },
                # Clip share endpoint
                {
                    "endpoint": "direct_v2/threads/broadcast/clip/",
                    "data": {
                        "media_id": str(media_id),
                        "recipient_users": f"[[{user_id}]]",
                        "client_context": self.client.generate_uuid(),
                        "_uid": str(self.client.user_id),
                        "_uuid": self.client.uuid,
                    }
                },
                # Generic share endpoint
                {
                    "endpoint": "direct_v2/threads/broadcast/share/",
                    "data": {
                        "media_id": str(media_id),
                        "media_type": "clips",
                        "recipient_users": f"[[{user_id}]]",
                        "client_context": self.client.generate_uuid(),
                        "_uid": str(self.client.user_id),
                        "_uuid": self.client.uuid,
                    }
                },
            ]

            for attempt in endpoints_to_try:
                try:
                    result = self.client.private_request(
                        attempt["endpoint"],
                        data=attempt["data"],
                        with_signature=False
                    )

                    if result.get("status") == "ok":
                        logger.info(f"Shared media {media_id} to user {username} via {attempt['endpoint']}")
                        return True
                except Exception as e:
                    logger.debug(f"Endpoint {attempt['endpoint']} failed: {e}")
                    continue

            # If all direct share methods fail, try sending as a link
            try:
                # Get the reel URL using the code (not media_id)
                if reel_code:
                    reel_url = f"https://www.instagram.com/reel/{reel_code}/"
                else:
                    reel_url = f"https://www.instagram.com/p/{media_id}/"

                # Use the library's direct_send method which is more reliable
                try:
                    thread = self.client.direct_send(
                        text=f"Check this out! {reel_url}",
                        user_ids=[int(user_id)]
                    )
                    if thread:
                        logger.info(f"Shared reel link to {username} via direct_send")
                        return True
                except Exception as e:
                    logger.debug(f"direct_send failed: {e}")

                # Fallback to raw API
                result = self.client.private_request(
                    "direct_v2/threads/broadcast/text/",
                    data={
                        "text": f"Check this out! {reel_url}",
                        "recipient_users": f"[[{user_id}]]",
                        "client_context": self.client.generate_uuid(),
                        "_uid": str(self.client.user_id),
                        "_uuid": self.client.uuid,
                    },
                    with_signature=False
                )
                if result.get("status") == "ok":
                    logger.info(f"Shared reel link to {username} via text message")
                    return True
            except Exception as e:
                logger.debug(f"Text share failed: {e}")

            logger.warning(f"All share methods failed for {username}")
            return False

        except RateLimitError:
            logger.error("Rate limited while sharing")
            raise
        except Exception as e:
            logger.error(f"Error sharing media {media_id} to {username}: {e}")
            return False

    def get_reel_thumbnail_url(self, media: Media) -> Optional[str]:
        """Get the thumbnail URL for a reel."""
        try:
            if media.thumbnail_url:
                return str(media.thumbnail_url)
            elif media.resources and len(media.resources) > 0:
                return str(media.resources[0].thumbnail_url)
        except Exception:
            pass
        return None

    def wait_with_jitter(self, base_delay: float = 4.0):
        """Wait with random jitter to avoid detection."""
        jitter = random.uniform(-1, 1)
        delay = max(2, base_delay + jitter)
        logger.debug(f"Waiting {delay:.1f} seconds...")
        time.sleep(delay)

    def cooldown(self, duration: int = 60):
        """Enter a cooldown period."""
        logger.info(f"Entering cooldown for {duration} seconds...")
        time.sleep(duration)
