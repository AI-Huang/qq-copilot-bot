"""Download QQ image attachments and extract metadata.

Images are saved under DATA_DIR/images/<sha256>.<ext>.
local_path stored in DB is relative to DATA_DIR (e.g. "images/abc123.jpg").
Files are content-addressed by SHA-256: identical images share one file on disk.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import httpx
from nonebot.log import logger
from PIL import Image as PILImage

from qq_copilot_bot.services.mysql.mysql_service import save_image
from settings import DATA_DIR

_IMAGE_DIR = DATA_DIR / "images"

# Mapping from Pillow format names to file extensions.
_FORMAT_EXT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "GIF": "gif",
    "WEBP": "webp",
    "BMP": "bmp",
}


async def process_image_segment(
    *,
    file_hash: str,
    url: str,
    user_id: int,
    session_id: str,
    group_id: int | None = None,
    message_id: str | None = None,
) -> None:
    """Download an image, extract metadata, and persist the record to MySQL.

    The file is saved as <sha256_of_content>.<ext> to avoid name collisions and
    deduplicate identical images. Failures are logged and swallowed so the event
    flow is never interrupted.
    """
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    mime_type: str | None = None
    local_path: str | None = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            data = resp.content

        file_size = len(data)
        content_sha256 = hashlib.sha256(data).hexdigest()

        with PILImage.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = img.format or "JPEG"
            mime_type = PILImage.MIME.get(fmt, f"image/{fmt.lower()}")

        ext = _FORMAT_EXT.get(fmt, fmt.lower())
        msg_dir = message_id if message_id else "unknown"
        file_name = f"{content_sha256}.{ext}"
        dest = _IMAGE_DIR / msg_dir / file_name
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not dest.exists():
            dest.write_bytes(data)
            logger.debug(
                "Image saved: {}/{} ({}×{}, {} bytes)",
                msg_dir, file_name, width, height, file_size,
            )
        else:
            logger.debug("Image already exists, skipping write: {}/{}", msg_dir, file_name)

        local_path = str(Path("images") / msg_dir / file_name)

    except Exception:
        logger.exception("Failed to download/process image {}", file_hash)

    save_image(
        file_hash=file_hash,
        url=url,
        user_id=user_id,
        session_id=session_id,
        group_id=group_id,
        message_id=message_id,
        local_path=local_path,
        width=width,
        height=height,
        file_size=file_size,
        mime_type=mime_type,
    )
