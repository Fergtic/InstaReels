#!/usr/bin/env python3
"""
Instagram Reels Auto-Engager

Automatically scrolls through Instagram Reels, analyzes them using AI,
and engages (likes, comments, shares) based on humor analysis.
"""

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from database import Database
from instagram_client import InstagramClient
from analyzer import ContentAnalyzer
from engager import Engager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("main")

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    logger.info("Shutdown signal received, finishing current reel...")
    shutdown_requested = True


def check_stop_file() -> bool:
    """Check if emergency stop file exists."""
    return Path("STOP").exists()


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Config file not found: {config_path}")
        logger.info("Creating default config file...")
        default_config = {
            "instagram_username": "",
            "instagram_password": "",
            "openai_api_key": "",
            "humor_threshold": 7,
            "comment_threshold": 8,
            "run_duration_minutes": 30,
            "delay_between_reels": 4,
            "max_reels_per_session": 50,
            "max_likes_per_day": 100,
            "max_comments_per_day": 20,
            "max_shares_per_day": 10,
            "cooldown_after_actions": 10,
            "cooldown_duration_seconds": 60
        }
        with open(path, "w") as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"Please fill in {config_path} and run again.")
        sys.exit(1)

    with open(path) as f:
        return json.load(f)


def validate_config(config: dict) -> bool:
    """Validate required config values."""
    required = ["instagram_username", "instagram_password", "openai_api_key"]

    missing = [k for k in required if not config.get(k)]
    if missing:
        logger.error(f"Missing required config values: {missing}")
        return False

    return True


def cleanup_temp_files(temp_dir: str = "temp_reels"):
    """Clean up temporary video files."""
    path = Path(temp_dir)
    if path.exists():
        shutil.rmtree(path)
        logger.info("Cleaned up temporary files")


def run_session(
    config: dict,
    dry_run: bool = False,
    analyze_only: bool = False
):
    """Run an engagement session."""
    global shutdown_requested

    # Initialize components
    logger.info("Initializing components...")

    db = Database()
    instagram = InstagramClient(
        username=config["instagram_username"],
        password=config["instagram_password"]
    )
    analyzer = ContentAnalyzer(config["openai_api_key"])
    engager = Engager(
        instagram_client=instagram,
        database=db,
        config=config,
        dry_run=dry_run or analyze_only
    )

    # Login to Instagram
    logger.info("Logging into Instagram...")
    if not instagram.login():
        logger.error("Failed to login to Instagram")
        return

    # Session parameters
    max_reels = config.get("max_reels_per_session", 50)
    delay = config.get("delay_between_reels", 4)
    run_duration = config.get("run_duration_minutes", 30)
    cooldown_after = config.get("cooldown_after_actions", 10)
    cooldown_duration = config.get("cooldown_duration_seconds", 60)

    session_end_time = datetime.now() + timedelta(minutes=run_duration)
    reels_processed = 0
    actions_since_cooldown = 0

    logger.info(f"Starting session: max {max_reels} reels, {run_duration} minutes")
    if dry_run:
        logger.info("DRY RUN MODE: No actual engagement will occur")
    if analyze_only:
        logger.info("ANALYZE ONLY: Just analyzing content, no engagement")

    try:
        # Fetch and process reels
        for reel_data in instagram.get_reels_feed(max_reels=max_reels):
            # Check stopping conditions
            if shutdown_requested:
                logger.info("Shutdown requested, stopping...")
                break

            if check_stop_file():
                logger.info("STOP file detected, stopping...")
                break

            if datetime.now() >= session_end_time:
                logger.info("Session time limit reached")
                break

            if reels_processed >= max_reels:
                logger.info("Max reels limit reached")
                break

            # Skip already analyzed reels
            reel_id = str(reel_data["pk"])
            if db.reel_already_analyzed(reel_id):
                logger.info(f"Reel {reel_id} already analyzed, skipping")
                continue

            # Extract info from reel_data dict
            username = reel_data.get("user", {}).get("username", "unknown")
            caption = reel_data.get("caption_text", "")
            reel_code = reel_data.get("code", "")
            thumbnail_url = reel_data.get("thumbnail_url")

            logger.info(f"\n{'='*50}")
            logger.info(f"Processing reel {reels_processed + 1}: {reel_id}")
            logger.info(f"Creator: @{username}")
            logger.info(f"Caption: {caption[:100]}..." if caption else "Caption: (none)")

            # Download reel
            video_path = instagram.download_reel(reel_data)
            if not video_path:
                logger.warning("Failed to download reel, skipping")
                continue

            try:
                # Analyze content
                logger.info("Analyzing content with GPT-4o...")
                analysis = analyzer.analyze_reel(
                    video_path=video_path,
                    caption=caption,
                    username=username
                )

                humor_score = analysis["humor_score"]
                humor_category = analysis["humor_category"]
                explanation = analysis["explanation"]
                suggested_comment = analysis["suggested_comment"]
                transcript = analysis["transcript"]

                logger.info(f"Humor Score: {humor_score}/10")
                logger.info(f"Category: {humor_category}")
                logger.info(f"Explanation: {explanation}")

                # Process engagement
                actions = []
                if not analyze_only:
                    actions = engager.process_engagement(
                        reel_id=reel_id,
                        humor_score=humor_score,
                        humor_category=humor_category,
                        suggested_comment=suggested_comment,
                        reel_code=reel_code
                    )
                    if actions:
                        logger.info(f"Actions taken: {actions}")
                        actions_since_cooldown += len(actions)

                # Save to database
                action_str = ",".join(actions) if actions else "none"

                db.save_reel_analysis(
                    reel_id=reel_id,
                    reel_code=reel_code,
                    username=username,
                    caption=caption,
                    humor_score=humor_score,
                    humor_category=humor_category,
                    humor_explanation=explanation,
                    transcript=transcript,
                    action_taken=action_str,
                    thumbnail_url=thumbnail_url
                )

                reels_processed += 1

                # Check if cooldown needed
                if actions_since_cooldown >= cooldown_after:
                    logger.info(f"Cooldown after {cooldown_after} actions...")
                    instagram.cooldown(cooldown_duration)
                    actions_since_cooldown = 0

            finally:
                # Clean up downloaded video
                if video_path and video_path.exists():
                    video_path.unlink()

            # Wait between reels
            instagram.wait_with_jitter(delay)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Session error: {e}", exc_info=True)
    finally:
        # Update daily stats
        db.update_daily_stats()

        # Session summary
        logger.info(f"\n{'='*50}")
        logger.info("SESSION COMPLETE")
        logger.info(f"Reels processed: {reels_processed}")
        summary = engager.get_engagement_summary()
        logger.info(f"Today's engagement: {summary}")

        # Cleanup
        cleanup_temp_files()
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Instagram Reels Auto-Engager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  # Run full automation
  python main.py --dry-run        # Analyze and simulate engagement
  python main.py --analyze-only   # Just analyze, no engagement at all
  python main.py --config my.json # Use custom config file

Safety:
  Create a file named 'STOP' in the current directory to halt execution.
        """
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Analyze reels but don't actually engage (simulates engagement)"
    )
    parser.add_argument(
        "--analyze-only", action="store_true",
        help="Only analyze reels, skip all engagement logic"
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Path to config file (default: config.json)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Remove any existing stop file
    Path("STOP").unlink(missing_ok=True)

    # Load and validate config
    config = load_config(args.config)
    if not validate_config(config):
        sys.exit(1)

    # Check for API key in environment as fallback
    if not config.get("openai_api_key"):
        config["openai_api_key"] = os.environ.get("OPENAI_API_KEY", "")

    if not config.get("openai_api_key"):
        logger.error("OpenAI API key not found in config or OPENAI_API_KEY env var")
        sys.exit(1)

    # Run the session
    logger.info("="*60)
    logger.info(" INSTAGRAM REELS AUTO-ENGAGER")
    logger.info(f" Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    run_session(
        config=config,
        dry_run=args.dry_run,
        analyze_only=args.analyze_only
    )


if __name__ == "__main__":
    main()
