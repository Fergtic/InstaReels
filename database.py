"""SQLite database operations for tracking Reels analysis and engagement."""

import sqlite3
from datetime import datetime, date
from typing import Optional
from pathlib import Path


class Database:
    def __init__(self, db_path: str = "reels_data.db"):
        self.db_path = db_path
        self.conn = None
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()

        # Reels analyzed table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reels_analyzed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reel_id TEXT UNIQUE NOT NULL,
                reel_code TEXT,
                username TEXT,
                caption TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                humor_score REAL,
                humor_category TEXT,
                humor_explanation TEXT,
                transcript TEXT,
                action_taken TEXT,
                thumbnail_url TEXT
            )
        """)

        # Engagement log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS engagement_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reel_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                friend_username TEXT,
                comment_text TEXT,
                success INTEGER DEFAULT 1,
                error_message TEXT,
                FOREIGN KEY (reel_id) REFERENCES reels_analyzed(reel_id)
            )
        """)

        # Daily stats table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL,
                total_analyzed INTEGER DEFAULT 0,
                total_liked INTEGER DEFAULT 0,
                total_commented INTEGER DEFAULT 0,
                total_shared INTEGER DEFAULT 0,
                avg_humor_score REAL DEFAULT 0
            )
        """)

        # Friend share tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friend_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                friend_username TEXT NOT NULL,
                date DATE NOT NULL,
                share_count INTEGER DEFAULT 0,
                UNIQUE(friend_username, date)
            )
        """)

        self.conn.commit()

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def reel_already_analyzed(self, reel_id: str) -> bool:
        """Check if a reel has already been analyzed."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM reels_analyzed WHERE reel_id = ?", (reel_id,))
        return cursor.fetchone() is not None

    def save_reel_analysis(
        self,
        reel_id: str,
        reel_code: str,
        username: str,
        caption: str,
        humor_score: float,
        humor_category: str,
        humor_explanation: str,
        transcript: str,
        action_taken: str,
        thumbnail_url: str = None
    ):
        """Save a reel analysis to the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO reels_analyzed
            (reel_id, reel_code, username, caption, humor_score, humor_category,
             humor_explanation, transcript, action_taken, thumbnail_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (reel_id, reel_code, username, caption, humor_score, humor_category,
              humor_explanation, transcript, action_taken, thumbnail_url))
        self.conn.commit()

    def log_engagement(
        self,
        reel_id: str,
        action_type: str,
        friend_username: str = None,
        comment_text: str = None,
        success: bool = True,
        error_message: str = None
    ):
        """Log an engagement action."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO engagement_log
            (reel_id, action_type, friend_username, comment_text, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (reel_id, action_type, friend_username, comment_text, int(success), error_message))
        self.conn.commit()

    def update_daily_stats(self):
        """Update daily statistics based on today's activity."""
        today = date.today().isoformat()
        cursor = self.conn.cursor()

        # Get today's counts
        cursor.execute("""
            SELECT COUNT(*) FROM reels_analyzed
            WHERE DATE(timestamp) = ?
        """, (today,))
        total_analyzed = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'like' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        total_liked = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'comment' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        total_commented = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'share' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        total_shared = cursor.fetchone()[0]

        cursor.execute("""
            SELECT AVG(humor_score) FROM reels_analyzed
            WHERE DATE(timestamp) = ?
        """, (today,))
        avg_score = cursor.fetchone()[0] or 0

        cursor.execute("""
            INSERT OR REPLACE INTO daily_stats
            (date, total_analyzed, total_liked, total_commented, total_shared, avg_humor_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today, total_analyzed, total_liked, total_commented, total_shared, avg_score))
        self.conn.commit()

    def get_daily_engagement_counts(self) -> dict:
        """Get today's engagement counts."""
        today = date.today().isoformat()
        cursor = self.conn.cursor()

        counts = {"likes": 0, "comments": 0, "shares": 0}

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'like' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        counts["likes"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'comment' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        counts["comments"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM engagement_log
            WHERE action_type = 'share' AND DATE(timestamp) = ? AND success = 1
        """, (today,))
        counts["shares"] = cursor.fetchone()[0]

        return counts

    def get_friend_share_count_today(self, friend_username: str) -> int:
        """Get how many shares a friend has received today."""
        today = date.today().isoformat()
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT share_count FROM friend_shares
            WHERE friend_username = ? AND date = ?
        """, (friend_username, today))
        result = cursor.fetchone()
        return result[0] if result else 0

    def increment_friend_share_count(self, friend_username: str):
        """Increment the share count for a friend today."""
        today = date.today().isoformat()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO friend_shares (friend_username, date, share_count)
            VALUES (?, ?, 1)
            ON CONFLICT(friend_username, date)
            DO UPDATE SET share_count = share_count + 1
        """, (friend_username, today))
        self.conn.commit()

    def get_daily_stats(self, days: int = 7) -> list:
        """Get daily stats for the last N days."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM daily_stats
            ORDER BY date DESC
            LIMIT ?
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]

    def get_top_reels(self, limit: int = 10) -> list:
        """Get the top rated reels."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM reels_analyzed
            ORDER BY humor_score DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_category_breakdown(self) -> list:
        """Get engagement breakdown by humor category."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                humor_category,
                COUNT(*) as count,
                AVG(humor_score) as avg_score,
                SUM(CASE WHEN action_taken LIKE '%like%' THEN 1 ELSE 0 END) as likes,
                SUM(CASE WHEN action_taken LIKE '%comment%' THEN 1 ELSE 0 END) as comments,
                SUM(CASE WHEN action_taken LIKE '%share%' THEN 1 ELSE 0 END) as shares
            FROM reels_analyzed
            GROUP BY humor_category
            ORDER BY count DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_friend_sharing_stats(self) -> list:
        """Get sharing stats per friend."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                friend_username,
                SUM(share_count) as total_shares,
                MAX(date) as last_share_date
            FROM friend_shares
            GROUP BY friend_username
            ORDER BY total_shares DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_engagements(self, limit: int = 20) -> list:
        """Get recent engagement activity."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                e.*,
                r.humor_score,
                r.humor_category,
                r.username as reel_author
            FROM engagement_log e
            LEFT JOIN reels_analyzed r ON e.reel_id = r.reel_id
            ORDER BY e.timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
