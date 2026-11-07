run

```
pip install -r requirements.txt
```

prior to running this software

In **Prepare media**, enable **Include subtitles** to select a WebVTT (`.vtt`)
file. Leave the file field blank to use the `.vtt` beside the source media with
the same basename. Subtitles are uploaded with the media and referenced in its
JSON metadata; video preparation also embeds them in the output video.

To update the website after uploading, enable **Update World Stage media links
after upload**. The song ID is found automatically from the filename's year,
country, and entry code: `ws1995pl.mp4` matches an entry without a code, while
`ws1995pl-final.mp4` matches entry code `final`. Missing or ambiguous matches stop
preparation before processing or uploading. S3 settings and a song API token
must be configured in Settings. Uploaded media, cover, and subtitle links
are updated; omitted cover/subtitle links are left unchanged.

Both Prepare media and Batch download read the current song before updating
links. An existing original link is left untouched. If the original field is
visible and empty, an external source URL can be saved there; a CDN URL is never
saved as the original.

The equivalent preparation CLI options are `--subtitles-file PATH`,
`--update-song-links`, placed before the `audio` or `video` subcommand.
`--song-id ID` remains an optional CLI override for automatic lookup.
`--subtitles` still selects the matching `.vtt` sidecar.
