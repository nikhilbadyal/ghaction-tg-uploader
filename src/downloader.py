"""Downloader."""
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import PriorityQueue
from time import perf_counter
from typing import Any, Dict, List, Self, Tuple

import aiohttp
import requests
from loguru import logger
from tqdm import tqdm

from src.config import UploaderConfig, session
from src.constant import REQUEST_TIMEOUT, temp_folder


class Downloader(object):
    """Downloader."""

    def __init__(self: Self, response: Dict[Any, Any], changes: str, config: UploaderConfig) -> None:
        self._CHUNK_SIZE = 10485760
        self._QUEUE: PriorityQueue[Tuple[float, str]] = PriorityQueue()
        self._QUEUE_LENGTH = 0
        self.response = response
        self.downloaded_files: List[str] = []
        self.changes = changes
        self.config = UploaderConfig

    @classmethod
    async def initialize(cls, config: UploaderConfig) -> Self:
        """Fetch the Latest Release from GitHub."""
        logger.debug("Fetching latest assets...")
        async with (
            aiohttp.ClientSession() as aio_session,
            aio_session.get(config.repo_url, timeout=REQUEST_TIMEOUT) as resp,
        ):
            response = resp.json()
            changelog_response = requests.get(config.changelog_url, timeout=REQUEST_TIMEOUT).json()
            if response.get("message") == "Not Found":
                logger.info(f"No Release found in {config.repo_url}. Exiting.")
                sys.exit(0)
            changes = changelog_response.get("html_url")
            return cls(response, changes, config)

    def __download(self: Self, assets_url: str, file_name: str) -> None:
        logger.debug(f"Trying to download {file_name} from {assets_url}")
        self._QUEUE_LENGTH += 1
        start = perf_counter()
        resp = session.get(assets_url, stream=True)
        total = int(resp.headers.get("content-length", 0))
        bar = tqdm(
            desc=file_name,
            total=total,
            unit="iB",
            unit_scale=True,
            unit_divisor=1024,
            colour="green",
        )
        if not Path(temp_folder).exists():
            Path(temp_folder).mkdir(parents=True)
        with temp_folder.joinpath(file_name).open("wb") as dl_file, bar:
            for chunk in resp.iter_content(self._CHUNK_SIZE):
                size = dl_file.write(chunk)
                bar.update(size)
        self._QUEUE.put((perf_counter() - start, file_name))
        logger.debug(f"Downloaded {file_name}")

    def __download_assets(self: Self, asset_url: str, file_name: str) -> None:
        self.__download(asset_url, file_name=file_name)

    def download_latest(self: Self, config: UploaderConfig) -> None:
        """Download all latest assets :return: List of downloaded assets."""
        assets_from_api = self.response["assets"]
        matched_assets: List[Tuple[Any, Any]] = []
        all_assets: List[Tuple[Any, Any]] = []
        for asset in assets_from_api:
            asset_url = asset["browser_download_url"]
            app_name = asset["name"]
            all_assets.append((asset_url, app_name))
        for asset in all_assets:
            if re.search(config.assets_pattern, asset[1]):
                self.downloaded_files.append(str(temp_folder) + "/" + asset[1])
                matched_assets.append(asset)
                logger.info(f"{asset[1]} matched.")
            else:
                logger.debug(f"Skipping {asset[1]}.")
        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(lambda repo: self.__download_assets(*repo), matched_assets)
        logger.info(f"Downloaded all assets {self.downloaded_files}")
