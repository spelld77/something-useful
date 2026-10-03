from __future__ import annotations

import unittest

from videodownloader.models import ErrorKind, Job, JobState, MediaInfo


class ModelTests(unittest.TestCase):
    def test_new_job_is_queued(self) -> None:
        job = Job("https://example.com/video")

        self.assertEqual(job.state, JobState.QUEUED)
        self.assertEqual(str(ErrorKind.HTTP_FORBIDDEN), "http_forbidden")

    def test_media_info_formats_resolution(self) -> None:
        media = MediaInfo(width=3840, height=2160, video_codec="av1")

        self.assertEqual(media.resolution, "3840×2160")


if __name__ == "__main__":
    unittest.main()
