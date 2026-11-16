from datetime import datetime

from pydantic import BaseModel


class SermonResource(BaseModel):
    """Shared Schema for single sermon from Ekklesia or Subsplash."""

    #: Link to the related audio resource, if one exists.
    audio: str | None

    #: Date at which the sermon was recorded.
    date: datetime

    #: Link to the related notes resource, if one exists.
    notes: str | None

    #: Unique identifier of the sermon. Some sermons on subsplash don't have this.
    sermon_id: int | None

    #: Title of the sermon.
    sermon_title: str

    #: Name of the sermon series.
    series: str

    #: Name of the sermon preacher | speaker.
    speaker: str

    #: Link to the related video resource, if one exists.
    video: str | None

    #: Size of the audio file in MB. This is not provided by Ekklesia, but can be calculated from the audio file size.
    audio_size_mb: float | None = None

    #: Size of the video file in MB. This is not provided by Ekklesia, but can be calculated from the video file size.
    video_size_mb: float | None = None

    #: Size of the notes file in MB. This is not provided by Ekklesia, but can be calculated from the notes file size.
    notes_size_mb: float | None = None
