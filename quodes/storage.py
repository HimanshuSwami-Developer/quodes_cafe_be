"""File storage for uploads: Cloudinary when CLOUDINARY_URL is set, local disk otherwise.

Two storages (see STORAGES in settings):
  * "default" – public assets (game covers). Plain Cloudinary `upload` URLs, cacheable by the CDN.
  * "private" – payment screenshots and ticket attachments. Stored with Cloudinary's
    `authenticated` delivery type, so a URL only works when it carries a signature made
    with the API secret. The API hands out signed URLs to the right people; nobody can
    guess or edit one to reach another player's screenshot.

The name saved in the database is the plain path (e.g. `proofs/2026/11/QG-ABC123-1a2b.png`),
so switching between disk and Cloudinary needs no schema change.
"""
import posixpath
import secrets
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import cloudinary.utils
import httpx
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage, storages
from django.utils.deconstruct import deconstructible

# Delivered as Cloudinary "image" assets (resizable, format-converted). Everything else,
# including PDFs (blocked for delivery on new Cloudinary accounts by default), goes as "raw".
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif", "avif"}


def configure(url):
    """Point the Cloudinary SDK at `cloudinary://<key>:<secret>@<cloud_name>`."""
    u = urlparse(url)
    if u.scheme != "cloudinary" or not (u.hostname and u.username and u.password):
        raise ValueError("CLOUDINARY_URL must look like cloudinary://<api_key>:<api_secret>@<cloud_name>")
    cloudinary.config(cloud_name=u.hostname, api_key=u.username, api_secret=u.password, secure=True)


def private_storage():
    """Storage for sensitive uploads. A callable, so migrations don't freeze the backend."""
    return storages["private"]


@deconstructible
class CloudinaryStorage(Storage):
    def __init__(self, delivery="upload", folder=None, max_width=None):
        self.delivery = delivery  # "upload" (public) or "authenticated" (signed URLs only)
        self.folder = (folder if folder is not None else getattr(settings, "CLOUDINARY_FOLDER", "")).strip("/")
        self.max_width = max_width  # downscale public images on delivery

    # ---- name <-> Cloudinary asset ------------------------------------------------
    def _asset(self, name):
        """(resource_type, public_id, format) for a stored name."""
        name = name.replace("\\", "/").lstrip("/")
        full = f"{self.folder}/{name}" if self.folder else name
        root, ext = posixpath.splitext(full)
        ext = ext.lstrip(".").lower()
        if ext in IMAGE_EXTS:
            return "image", root, ext
        return "raw", full, None  # raw public IDs keep their extension

    # ---- Storage API ----------------------------------------------------------------
    def _save(self, name, content):
        name = name.replace("\\", "/").lstrip("/")
        for attempt in range(5):
            rtype, public_id, _ = self._asset(name)
            content.seek(0)
            res = cloudinary.uploader.upload(
                content, public_id=public_id, resource_type=rtype, type=self.delivery,
                overwrite=False, unique_filename=False, use_filename=False, invalidate=True)
            if not res.get("existing"):
                return name
            # Name taken: Cloudinary kept the old file. Add a suffix and try again.
            root, ext = posixpath.splitext(name)
            name = f"{root}-{secrets.token_hex(3)}{ext}"
        raise OSError(f"Could not find a free Cloudinary name for {name}")

    def exists(self, name):
        # Upload uses overwrite=False and retries on a clash, so no Admin API call is needed here.
        return False

    def url(self, name):
        rtype, public_id, fmt = self._asset(name)
        opts = {"resource_type": rtype, "type": self.delivery, "secure": True}
        if fmt:
            opts["format"] = fmt
        if self.delivery != "upload":
            opts["sign_url"] = True
        if rtype == "image" and self.max_width:
            opts.update(width=self.max_width, crop="limit", quality="auto")
        return cloudinary.utils.cloudinary_url(public_id, **opts)[0]

    def delete(self, name):
        if not name:
            return
        rtype, public_id, _ = self._asset(name)
        cloudinary.uploader.destroy(public_id, resource_type=rtype, type=self.delivery, invalidate=True)

    def _open(self, name, mode="rb"):
        # Original bytes (no resize), e.g. for the AI scan of a payment screenshot.
        rtype, public_id, fmt = self._asset(name)
        opts = {"resource_type": rtype, "type": self.delivery, "secure": True,
                "sign_url": self.delivery != "upload"}
        if fmt:
            opts["format"] = fmt
        r = httpx.get(cloudinary.utils.cloudinary_url(public_id, **opts)[0], timeout=30, follow_redirects=True)
        r.raise_for_status()
        return ContentFile(r.content, name=name)

    def size(self, name):
        return self._open(name).size
