# MediaSorter

A Python script that keeps a media library (short videos, images, screenshots, WhatsApp media folders and other files) organised in a consistent folder tree, with a consistent, content-aware name for every file.

## What it does

Every run re-sorts the whole library, so changes to the sorting rules apply to all files.

1. Renames `ROOT_DIR\media` (the library) to `ROOT_DIR\source` and creates an empty `media`.
2. Renames each file to `username--quickid.ext`:
   - No date or time in the name. The date is read from the file's last-modified time and used for the video folders.
   - The username is taken from the original filename and cut to 50 characters. Once a file has been sorted, its username never changes.
   - The quick ID is a fast fingerprint of the file's size and a few sampled bytes.
3. Moves each file back into `media`:

   | Condition (first match wins)          | Destination                            |
   |---------------------------------------|----------------------------------------|
   | Image/video extension, but the content isn't an image or video | `media\CHECK` |
   | Filename contains "screenshot"        | `media\SPECIAL\SCREENSHOTS`            |
   | Source path contains "special"        | `media\SPECIAL\<sub-path after SPECIAL>` |
   | Image (jpg, png, webp, heic, …)       | `media\IMAGES`                         |
   | Video (`.mp4`)                        | `media\DATED\YYYY\YYYY-MM\YYYY-MM-DD`  |
   | Anything else                         | `media\OTHERS`                         |

4. Deletes `source` once it's empty. Files that failed to move stay there for review, and the next run picks them up.

It never overwrites or deletes files. Copies of the same file in a folder are all kept, with `-1`, `-2`, `-3`… added before the extension. Logs go to `ROOT_DIR\LOGS`, including a dated index of every original path and its new path.

## Usage

1. Set `ROOT_DIR` at the top of `media_sorter.py`.
2. Drop new files anywhere in `ROOT_DIR\media`.
3. Move any folders whose structure must be kept into `ROOT_DIR\media\SPECIAL\`. Everything outside it is flattened by type and date.
4. Close any program or Explorer window that has something in `media` open.
5. Run:

```bash
python media_sorter.py
```

Requires Python 3 and only the standard library.

> **Warning:** there is no dry-run mode. Every run moves files immediately.

See [aaa.md](aaa.md) for detailed notes on how the script works and the decisions behind it.
