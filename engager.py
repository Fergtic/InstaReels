"""Engagement logic for liking, commenting, and sharing Reels."""

import json
import logging
from pathlib import Path
from typing import Optional

from database import Database
from instagram_client import InstagramClient

logger = logging.getLogger(__name__)


class FriendProfile:
    def __init__(self, username: str, interests: list[str], max_shares_per_day: int):
        self.username = username
        self.interests = [i.lower() for i in interests]
        self.max_shares_per_day = max_shares_per_day

    def matches_category(self, category: str) -> bool:
        """Check if a humor category matches this friend's interests."""
        category_lower = category.lower()
        return any(
            interest in category_lower or category_lower in interest
            for interest in self.interests
        )


class Engager:
    def __init__(
        self,
        instagram_client: InstagramClient,
        database: Database,
        config: dict,
        friends_config_path: str = "friends_config.json",
        dry_run: bool = False
    ):
        self.instagram = instagram_client
        self.db = database
        self.config = config
        self.dry_run = dry_run
        self.friends = self._load_friends(friends_config_path)
        self._sync_friends_to_db()

        # Extract config values with defaults
        self.humor_threshold = config.get("humor_threshold", 7)
        self.comment_threshold = config.get("comment_threshold", 8)
        self.max_likes_per_day = config.get("max_likes_per_day", 100)
        self.max_comments_per_day = config.get("max_comments_per_day", 20)
        self.max_shares_per_day = config.get("max_shares_per_day", 10)

    def _load_friends(self, config_path: str) -> list[FriendProfile]:
        """Load friend profiles from config file."""
        friends = []
        path = Path(config_path)

        if not path.exists():
            logger.warning(f"Friends config not found: {config_path}")
            return friends

        try:
            with open(path) as f:
                data = json.load(f)

            for friend_data in data.get("friends", []):
                friend = FriendProfile(
                    username=friend_data["username"],
                    interests=friend_data.get("interests", []),
                    max_shares_per_day=friend_data.get("max_shares_per_day", 3)
                )
                friends.append(friend)

            logger.info(f"Loaded {len(friends)} friend profiles")

        except Exception as e:
            logger.error(f"Error loading friends config: {e}")

        return friends

    def _sync_friends_to_db(self):
        """Remove friend_shares entries for friends no longer in the config."""
        current_usernames = [f.username for f in self.friends]
        if not current_usernames:
            return
        placeholders = ",".join("?" * len(current_usernames))
        cursor = self.db.conn.cursor()
        cursor.execute(
            f"DELETE FROM friend_shares WHERE friend_username NOT IN ({placeholders})",
            current_usernames
        )
        if cursor.rowcount > 0:
            logger.info(f"Cleaned up {cursor.rowcount} stale friend_shares entries")
        self.db.conn.commit()

    def _can_like(self) -> bool:
        """Check if we can perform more likes today."""
        counts = self.db.get_daily_engagement_counts()
        return counts["likes"] < self.max_likes_per_day

    def _can_comment(self) -> bool:
        """Check if we can perform more comments today."""
        counts = self.db.get_daily_engagement_counts()
        return counts["comments"] < self.max_comments_per_day

    def _can_share(self) -> bool:
        """Check if we can perform more shares today."""
        counts = self.db.get_daily_engagement_counts()
        return counts["shares"] < self.max_shares_per_day

    def _can_share_to_friend(self, friend: FriendProfile) -> bool:
        """Check if we can share more to this specific friend today."""
        share_count = self.db.get_friend_share_count_today(friend.username)
        return share_count < friend.max_shares_per_day

    def process_engagement(
        self,
        reel_id: str,
        humor_score: float,
        humor_category: str,
        suggested_comment: str = "",
        reel_code: str = ""
    ) -> list[str]:
        """
        Process engagement decisions for a reel.

        Returns list of actions taken: ['like', 'comment', 'share:username']
        """
        actions = []

        # Like decision
        if humor_score >= self.humor_threshold:
            if self._can_like():
                success = self._do_like(reel_id)
                if success:
                    actions.append("like")
            else:
                logger.info("Daily like limit reached")

        # Comment decision
        if humor_score >= self.comment_threshold and suggested_comment:
            if self._can_comment():
                success = self._do_comment(reel_id, suggested_comment)
                if success:
                    actions.append("comment")
            else:
                logger.info("Daily comment limit reached")

        # Share decision
        if self._can_share():
            matching_friends = self._find_matching_friends(humor_category)
            for friend in matching_friends:
                if self._can_share_to_friend(friend):
                    success = self._do_share(reel_id, friend, reel_code)
                    if success:
                        actions.append(f"share:{friend.username}")
                        # Only share to one friend per reel to avoid spam
                        break

        return actions

    def _find_matching_friends(self, humor_category: str) -> list[FriendProfile]:
        """Find friends whose interests match the humor category."""
        return [f for f in self.friends if f.matches_category(humor_category)]

    def _do_like(self, reel_id: str) -> bool:
        """Perform a like action."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would like reel: {reel_id}")
            self.db.log_engagement(reel_id, "like", success=True)
            return True

        try:
            success = self.instagram.like_media(reel_id)
            self.db.log_engagement(reel_id, "like", success=success)
            return success
        except Exception as e:
            logger.error(f"Failed to like reel: {e}")
            self.db.log_engagement(reel_id, "like", success=False, error_message=str(e))
            return False

    def _do_comment(self, reel_id: str, comment_text: str) -> bool:
        """Perform a comment action."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would comment on reel {reel_id}: {comment_text}")
            self.db.log_engagement(reel_id, "comment", comment_text=comment_text, success=True)
            return True

        try:
            success = self.instagram.comment_media(reel_id, comment_text)
            self.db.log_engagement(
                reel_id, "comment",
                comment_text=comment_text,
                success=success
            )
            return success
        except Exception as e:
            logger.error(f"Failed to comment on reel: {e}")
            self.db.log_engagement(
                reel_id, "comment",
                comment_text=comment_text,
                success=False,
                error_message=str(e)
            )
            return False

    def _do_share(self, reel_id: str, friend: FriendProfile, reel_code: str = "") -> bool:
        """Perform a share action."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would share reel {reel_id} to @{friend.username}")
            self.db.log_engagement(
                reel_id, "share",
                friend_username=friend.username,
                success=True
            )
            self.db.increment_friend_share_count(friend.username)
            return True

        try:
            success = self.instagram.share_media_to_user(reel_id, friend.username, reel_code)
            self.db.log_engagement(
                reel_id, "share",
                friend_username=friend.username,
                success=success
            )
            if success:
                self.db.increment_friend_share_count(friend.username)
            return success
        except Exception as e:
            logger.error(f"Failed to share reel to {friend.username}: {e}")
            self.db.log_engagement(
                reel_id, "share",
                friend_username=friend.username,
                success=False,
                error_message=str(e)
            )
            return False

    def get_engagement_summary(self) -> dict:
        """Get a summary of today's engagement."""
        counts = self.db.get_daily_engagement_counts()
        return {
            "likes": f"{counts['likes']}/{self.max_likes_per_day}",
            "comments": f"{counts['comments']}/{self.max_comments_per_day}",
            "shares": f"{counts['shares']}/{self.max_shares_per_day}"
        }
