import json
import logging
import os
from datetime import datetime
from pathlib import Path

from instaloader.instaloader import Instaloader
from instaloader.lateststamps import LatestStamps
from instaloader.structures import Highlight, Profile, Story


# TODO: use latest stamps and setup the scheduling for the timing of the runs
class InstagramMonitor:
    # Declare class attributes with optional types
    data_dir: Path
    highlights_dir: Path
    stories_dir: Path
    data_file: Path
    highlights_file: Path
    stories_file: Path
    metadata_file: Path

    def __init__(self, profile_username, insta_loader: Instaloader) -> None:
        self.profile_username = profile_username

        self.profile_id_file = f"{profile_username}_profile_id.json"

        # Define base directory using profile_username
        self.data_dir = Path("output", f"{profile_username}_data")

        # Set up directory and file variables, creating if needed
        self.setup_dirs()

        # Setup metadata file
        self.metadata_file = self.data_dir / "metadata.json"
        self.setup_metadata_file()

        self.data_file_mapping = {
            "data": self.data_file,
            "downloaded_highlights": self.highlights_file,
            "downloaded_stories": self.stories_file,
        }

        self.downloaded_highlights_list: list = []
        self.downloaded_stories_list: list = []
        self.data = {}

        # Setup logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

        # initialize Instaloader
        self.L = insta_loader

    def setup_dirs(self):
        # Define directory and file paths
        dir_file_mapping = {
            "highlights_dir": self.data_dir / "highlights",
            "stories_dir": self.data_dir / "stories",
            "data_file": self.data_dir / "data.json",
            "highlights_file": self.data_dir.joinpath(
                "highlights", "downloaded_highlights.json"
            ),
            "stories_file": self.data_dir.joinpath(
                "stories", "downloaded_stories.json"
            ),
        }

        # Create attributes using setattr
        for attr_name, path in dir_file_mapping.items():
            setattr(self, attr_name, path)
            # Create directory if it doesn't exist
            if attr_name.endswith("_dir"):
                path.mkdir(parents=True, exist_ok=True)

    def setup_metadata_file(self):
        # Setup the metadata file with the top level keys for the different types
        if not self.metadata_file.exists():
            initial_metadata = {
                "highlights": {},
                "stories": {},
            }

            with open(self.metadata_file, "w", encoding="utf-8") as file:
                json.dump(initial_metadata, file, indent=4)

    def setup(self):
        os.makedirs(self.data_dir, exist_ok=True)
        self.load_data()

    def load_data(self):
        for data_key, filename in self.data_file_mapping.items():
            self.__dict__[data_key] = self.load_json(filename)

    def save_data(self):
        for data_key, filename in self.data_file_mapping.items():
            self.save_json(filename, self.__dict__[data_key])

    def load_json(self, filename):
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as file:
                return json.load(file)
        return {}

    def save_json(self, filename, json_data):
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(json_data, file, indent=4)

    def update_metadata_file(self, category_key: str, new_metadata, timestamp: str):
        """Update global metadata file with timestamped entry for a category key (highlights, stories)"""

        with open(self.metadata_file, "r+", encoding="utf-8") as file:
            metadata = json.load(file)

            if timestamp not in metadata[category_key]:
                metadata[category_key][timestamp] = {}
            metadata[category_key][timestamp].update(new_metadata)
            file.seek(0)
            json.dump(metadata, file, indent=4)

    def compare_and_log_changes(self, old_list, new_list, list_name):
        added = set(new_list) - set(old_list)
        removed = set(old_list) - set(new_list)
        if added:
            self.logger.info("New %s: %s", list_name, added)
        if removed:
            self.logger.info("Removed %s: %s", list_name, removed)

    def download_new_highlights(self, target_profile: Profile, timestamp: str):
        new_downloads = []
        downloaded_ids = set(self.downloaded_highlights_list)

        for highlight in self.L.get_highlights(target_profile.userid):
            if highlight.unique_id not in downloaded_ids:
                self.logger.info(
                    "Downloading new highlight: %s with %d highlight members",
                    highlight.title,
                    highlight.itemcount,
                )
                self.download_highlights_with_metadata(highlight, timestamp)
                new_downloads.append(highlight.unique_id)

        return new_downloads

    def download_highlights_with_metadata(self, highlight: Highlight, timestamp: str):
        # Save metadata for the whole highlight
        highlights_metadata = {
            "id": highlight.unique_id,
            "title": highlight.title,
            # "latest_story_creation_time": highlight.latest_media_utc.strftime(
            #    "%Y-%m-%d %H:%M:%S"
            # ),
            "cover_url": highlight.cover_url,
            "highlight_count": highlight.itemcount,
            "stories": [],
        }

        # item is a StoryItem
        # get metadata for each highlight in the highlights
        for item in highlight.get_items():
            # Download the items within the highlight
            self.L.download_storyitem(item, target=self.highlights_dir)

            item_metadata = {
                "media_id": item.mediaid,
                "url": item.url,
                # "created_at": item.date_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "caption": item.caption,
                "caption_mentions": item.caption_mentions,
                "is_video": item.is_video,
                "video_url": item.video_url if item.is_video else None,
            }
            highlights_metadata["stories"].append(item_metadata)

        self.update_metadata_file("highlights", highlights_metadata, timestamp)

    def download_new_stories(self, target_profile: Profile, timestamp: str):
        new_downloads = []
        downloaded_ids = set(self.downloaded_stories_list)

        # story is a Story object
        for story in self.L.get_stories([target_profile.userid]):
            self.logger.info(
                "Downloading new story with the last created story at: %s",
                story.latest_media_utc,
            )
            self.download_stories_with_metadata(story, timestamp)
        return new_downloads

    def download_stories_with_metadata(self, story: Story, timestamp: str):
        stories_metadata = {
            "id": story.unique_id,
            "last_seen": (
                story.last_seen_utc.strftime("%Y-%m-%d %H:%M:%S")
                if story.last_seen_utc is not None
                else None
            ),
            "latest_media": story.latest_media_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "story_count": story.itemcount,
            "stories": [],
        }

        for story_item in story.get_items():
            self.L.download_storyitem(story_item, target=self.stories_dir)

            story_item_metadata = {
                "media_id": story_item.mediaid,
                "url": story_item.url,
                "created_at": story_item.date.strftime("%Y-%m-%d %H:%M:%S"),
                "expires_at": story_item.expiring_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "caption": story_item.caption,
                "caption_mentions": story_item.caption_mentions,
                "is_video": story_item.is_video,
                "video_url": story_item.video_url if story_item.is_video else None,
            }
            stories_metadata["stories"].append(story_item_metadata)

        self.update_metadata_file("stories", stories_metadata, timestamp)

    def fetch_or_save_profile_id(self, return_id=False):
        # If return_id is false (default) save to file
        # If return_id is true return the id and don't save to file

        # Fetch profile ID from Instagram
        target_profile = Profile.from_username(self.L.context, self.profile_username)
        profile_id = target_profile.userid

        # Return ID if requested
        if return_id:
            return profile_id

        # Save the profile ID otherwise
        with open(self.profile_id_file, "w", encoding="utf-8") as file:
            json.dump({"profile_id": profile_id}, file, indent=4)

    def check_and_update_profile_id(self):
        try:
            # Check if the profile ID file exists
            if not os.path.exists(self.profile_id_file):
                self.logger.info(
                    "Profile ID file not found. Fetching from Instagram..."
                )
                self.fetch_or_save_profile_id()

            # Load profile id from fille
            with open(self.profile_id_file, "r", encoding="utf-8") as file:
                stored_profile_id = json.load(file)["profile_id"]

            # Fetch the current profile ID from Instagram
            current_profile_id = self.fetch_or_save_profile_id(return_id=True)

            # Compare and update if neccessary
            if stored_profile_id != current_profile_id:
                self.logger.info("Profile ID has changed. Updating profile ID file...")
                self.fetch_or_save_profile_id()
            self.logger.info("Profile ID is up-to-date")
        except Exception as exc:
            # TODO: more precise in the future
            self.logger.error(
                "Error checking or updating profile ID %s", exc, exc_info=True
            )
            raise

    def update_profile_info(self, profile: Profile, timestamp: str):
        # Fetch information about the profile
        current_followers_count = profile.followers
        current_following_count = profile.followees
        biography = profile.biography
        profile_pic_url = profile.profile_pic_url

        current_followers = [
            (follower.userid, follower.username) for follower in profile.get_followers()
        ]
        current_following = [
            (followee.userid, followee.username) for followee in profile.get_followees()
        ]

        # Save the data dictionary under the timestamp key
        self.data[timestamp] = {
            "followers_count": current_followers_count,
            "following_count": current_following_count,
            "bio": biography,
            "profile_pic_url": profile_pic_url,
            "followers": current_followers,
            "following": current_following,
        }

        # Save updated data
        self.save_data()

    def run_monitor(self):
        try:
            self.setup()
            target_profile = Profile.from_username(
                self.L.context, self.profile_username
            )
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Download new highlights
            new_downloaded_highlights = self.download_new_highlights(
                target_profile, timestamp
            )

            self.downloaded_highlights_list.extend(new_downloaded_highlights)
            self.save_data()

            # Downlaod new stories
            new_downloaded_stories = self.download_new_stories(
                target_profile, timestamp
            )
            self.downloaded_stories_list.extend(new_downloaded_stories)
            self.save_data()

            # Update profile information
            self.update_profile_info(target_profile, timestamp)

            # Download tagged posts and profile picture
            self.L.download_profile(
                self.profile_username,
                profile_pic=True,
                download_stories=False,
                download_tagged=True,
            )

        except Exception as e:
            self.logger.error("Error monitoring profile: %s", e)
            raise
