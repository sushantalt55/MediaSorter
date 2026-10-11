# MediaSorter

| | |
|---|---|
| Code | `media_sorter.py`, a single file, standard library only (Python 3) |
| Repo | https://github.com/sushantalt55/MediaSorter |
| Data | `C:\Susi\MediaCurrent\` (not in the repo) |

---

## 1. What it is

Keeps a media library (short videos, images, screenshots, WhatsApp media folders etc.) in a tidy folder tree. Each file gets a short uniform name: username and content fingerprint. No date or time in the name: the date is always read from the file's modified time. Copies of the same file end up side by side as `name`, `name-1`, `name-2`…, and files that only pretend to be media are set aside in `CHECK`. **Every run re-sorts the whole library** with the current logic, so rule changes apply to everything. New files are simply dropped into the library.

---

## 2. Big picture

```
 C:\Susi\MediaCurrent\           ← ROOT_DIR
 │
 ├── media\    THE LIBRARY. Also the drop zone: put new files anywhere in it.
 │   └── SPECIAL\   folders whose structure must be kept. PUT THEM HERE BEFORE THE RUN.
 │
 │   ┌──────────────────────────── media_sorter.py ───────────────────────────┐
 │   │ 0. SWAP         rename media\ → source\, create an empty media\         │
 │   │                 (if source\ already exists: resume, sort only that)     │
 │   │ 1. COLLECT      list all files under source\                            │
 │   │ 2. READ         per file, 24 threads in parallel:                       │
 │   │                 quick_id + media check (first bytes = image/video?)     │
 │   │ 3. PER FILE                                                             │
 │   │      a. type      image / mp4 / unknown (from the extension)            │
 │   │      b. date      from the modified time (only for DATED folders)       │
 │   │      c. username  already-sorted name → reuse it; else regex rules;     │
 │   │                   cut to 50 chars                                       │
 │   │      d. new name  USER--FINGERPRINT.ext                                 │
 │   │      e. folder    see the rules below                                   │
 │   │      f. name taken → add -1, -2, -3 …                                   │
 │   │      g. MOVE      source\ → media\ (os.rename, never overwrites)        │
 │   │ 4. LOGS         CSV/TXT files in LOGS\                                  │
 │   │ 5. CLEANUP      delete the empty folders in source\, then source\       │
 │   │                 Files that failed to move stay in source\.              │
 │   └─────────────────────────────────────────────────────────────────────────┘
 │
 ├── source\   Exists only during a run, or after a run where some files failed.
 │
 │   media\ after a run. The first rule that matches wins, top to bottom:
 │   ├── CHECK\                          image/mp4 extension, but the content isn't media
 │   ├── SPECIAL\SCREENSHOTS\            filename contains "screenshot"
 │   ├── SPECIAL\<sub-path>\             source path contains "SPECIAL"
 │   ├── IMAGES\                         jpg png webp heic gif bmp tiff jfif
 │   ├── DATED\YYYY\YYYY-MM\YYYY-MM-DD\  .mp4
 │   └── OTHERS\                         everything else (unknown extensions)
 │
 └── LOGS\     file_index.csv = old path → new path (last run).
               index_history\ = a dated copy of it for every run.
```

**Example**

```
media\new\john_doe2025_06_15_14_30.mp4   (modified 2025-06-15 14:30:03, 5 bytes)
  → media\DATED\2025\2025-06\2025-06-15\john_doe--5--28ff9a91f84b.mp4
                                         └─user─┘ └fingerprint─┘
A second copy of the same file in that folder → john_doe--5--28ff9a91f84b-1.mp4
Next runs: same name, same place (unless the folder rules changed).
```

**Key rules**
1. Always moves files. No dry run.
2. Never overwrites or deletes files. A name clash becomes `name-1.ext`, `name-2.ext`… Only empty folders are deleted.
3. **No date or time in the filename.** The date comes from the modified time and only shows in the `DATED` folders. In the flat folders (`IMAGES`, `OTHERS`, `SPECIAL`, `CHECK`), sort by "Date modified".
4. Only folders under `media\SPECIAL\` keep their structure. Everything else is flattened into `IMAGES` / `DATED` / `OTHERS`.
5. **A username is fixed the first time a file is sorted** (cut to 50 characters). Later username-rule changes only affect new files.
6. `CHECK` beats every other rule, even `SPECIAL`.

---

## 3. Run

1. `ROOT_DIR` (top of the script) = `C:\Susi\MediaCurrent`.
2. Drop new files anywhere in `media\`. **Move folders whose structure must be kept into `media\SPECIAL\`.** For example, `media\SPECIAL\WhatsApp\Media\x.jpg` → `media\SPECIAL\WhatsApp\Media\<new name>.jpg`.
3. **Close anything that has a file or folder in `media\` open** (player, Explorer preview, terminal). Otherwise the rename at the start fails and the script stops without changing anything.
4. Run:
   ```bash
   python media_sorter.py
   ```
5. Check the summary (also in `LOGS\run_logs.txt`):
   - `Source folder: removed (empty)` → all good.
   - `Source folder: KEPT` → `source\` holds **only** the files that failed, in their original folders. See `files_not_moved.csv`. Fix the cause and run again: it resumes and sorts just those files.
   - `Suspected non-media (CHECK): N` → review `media\CHECK\`.

---

## 4. Code map

Section names match the `# ----` banners in the script.

| Section | Does |
|---|---|
| CONFIGURATION | `ROOT_DIR` → `MEDIA_DIR` (= `TARGET_DIR`), `SOURCE_DIR`, `LOGS_DIR`, `INDEX_HISTORY_DIR`; extension sets; `USERNAME_MAX_LEN = 50`. |
| `get_file_type(ext)` | Returns `"image"`, `"mp4"` or `None` (unknown → `OTHERS`). |
| `looks_like_media(path)` | Reads the first 12 bytes and checks them against image/video signatures. |
| `file_checks(path)` | `quick_id` + `looks_like_media` together, for the thread pool. |
| `sanitize(text)` | Replaces characters Windows doesn't allow in names, **plus `.`**, with `_`. |
| `quick_id(path)` | Returns `"<size>--<12 hex>"`. Hashes 128 B from the start, middle and end (start only if the file is 4 KB or less). |
| `remove_empty_dirs(path)` | Bottom-up `os.rmdir`; only removes empty folders, never files. |
| `SORTED_NAME` | Regex that recognises a name this script produced, in the current format and the two older ones (time or date+time in front). |
| `extract_username(filename)` | Rule 0 (already sorted → reuse the username), then the regex rule chain, then the 50-character cap. |
| FILE ORGANIZATION RULES | Comment with the original plan, partly out of date. Section 2 here is correct. |
| MAIN PROCESSING | Swap/resume → collect → read (thread pool) → per-file loop (name, folder, `-N`, move) → logs → cleanup. |
| Summary (end of file, **outside** the main guard) | Stats → `run_logs.txt` and the console. |

---

## 5. Detailed logic

**Swap / resume.**
- `source\` doesn't exist → rename `media\` → `source\` and create an empty `media\`.
- `source\` exists → leftovers from a failed run. Sort only those into the existing `media\`; the library isn't re-sorted this time.
- Neither exists → exit. No files found → remove the empty `source\` and exit.

**Media check → `CHECK\`.**
- **Applies only to files with an image/mp4 extension.** Unknown extensions still go to `OTHERS`.
- **Media** = the first bytes match JPEG, PNG, GIF, BMP, TIFF, WEBP, AVI, MKV/WEBM or an ISO box (`ftyp`, `moov`, `mdat`… = mp4/mov/heic).
- **Wrong extensions are fine.** Any media signature counts for any media extension, so a WEBP saved as `.jpg` is still media.
- **What lands in `CHECK`:** empty files, macOS `._` metadata files (they start with `00 05 16 07` and are usually 4096 B), text or HTML saved as `.jpg`, and unreadable files.

**Username rules.** They run in this order:
0. **Already sorted** (the name matches `user--size--hash[-N].ext`, or the older `HHMMSS--…` / `YYYY-MM-DD--HHMMSS--…`) → reuse `user` and stop. This keeps usernames stable across runs, including empty ones, ones containing `-`, and odd ones like `123_`.
1. Generic: split the full filename (extension included) on `-` and take the first piece that contains a letter. `john-doe.mp4` → `john`. With no `-`: `notes.txt` → `notes_txt`.
2. Starts with `IMG_` → `Threads`.
3. Text before `YYYY_MM_DD_HH_MM`: `john_doe2025_06_15_14_30.mp4` → `john_doe`.
4. Starts with `Screenshot` (case-sensitive) → `Screenshot`.
5. Contains `YT and Tik`, `tik (` or `yt (` (any case) → `tiktok`.
6. Then `sanitize()`. If nothing matched → `someone` (rare, because of rule 1).

Rules 1–5: the last match wins. Every result, rule 0 included, is cut to `USERNAME_MAX_LEN` (50). Cutting is stable: a 50-character username stays the same on later runs. To add a new format, put a rule near the bottom, before `sanitize`.

**Date.** From the modified time; only used for the `DATED\…` folders. `os.rename` keeps the modified time, so a file stays in the same date folder across runs.

**Folder.** CHECK → screenshot in the filename → SPECIAL in the source path → image → mp4 → others.
- SPECIAL: everything after the **last** "SPECIAL" in the path is kept under `media\SPECIAL\`. Files are still renamed.
- A screenshot or a `CHECK` file inside `SPECIAL` goes to its own folder, and its sub-path is **not** kept.

**Duplicates.** Same username + same content = same name. Tries `-1`, `-2`… until a name is free. This is per folder: copies in different folders (e.g. different date folders) all keep the plain name. Each run sorts into a fresh `media\`, so the `-N` numbering is redone every run. The clashing name goes in `existing_files.txt`.

---

## 6. Logs (`ROOT_DIR\LOGS`)

| File | Content | Kept? |
|---|---|---|
| `file_index.csv` | One row per file: old path, type, date, user, quick_id, new name, folder, moved | Overwritten |
| `index_history\file_index_<date_time>.csv` | Copy of the above per run. **The only record of original filenames.** | **Kept** |
| `run_logs.txt` | Summary per run | **Appended** |
| `files_not_moved.csv` | Move failures + error | Overwritten |
| `existing_files.txt` | Clashing names (the file got `-N`) | Overwritten |
| `username_errors.csv` | Fell back to `someone` | Overwritten |
| `temp_files.txt` | Unknown extensions (→ `OTHERS`) | Overwritten |

`index_history` grows by one file per run (≈150k rows each for the full library). Prune old ones by hand if needed.

---

## 7. Changing the code

**Frozen:**
- **`quick_id()` and the filename format `user--size--hash.ext`.** Both are tested.
- **`SORTED_NAME`.** It must match the current format (and keeps matching the older ones). If you ever change the format, update it too, or every existing username gets re-extracted from the sorted names (and changes).

**Safe to change** (re-applied to the whole library on the next run):
- **Extension sets.** Only `.mp4` counts as video; `.mov`/`.mkv` → `OTHERS`.
- **Media signatures in `looks_like_media()`.** If real media shows up in `CHECK`, add its signature here.
- **Folder rules** (the order matters).
- **`max_workers=24`.** Use about 4 on a spinning HDD.

**Username rules and `USERNAME_MAX_LEN`:** safe to change, but they **only affect files not yet sorted**. A smaller cap does shorten existing names too; a bigger one can't restore cut text. To re-apply rules to old files, take the original names from `index_history`.

**Test on a copy:**
1. Point the copy's `ROOT_DIR` at a temp folder.
2. Make dummy files in `<temp>\media\`, with real first bytes (e.g. `FF D8 FF` for jpg), and set their dates with `touch -d "2025-06-15 14:30:03" x.mp4`.
3. Run it twice; the second run must give identical names.

To limit a run to N files, uncomment `if processed_count > 10000: break`. Files skipped this way stay in `source\`, and the next run resumes with them.

---

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| `Cannot rename ... media ... to ... source` | Something has a file or folder in `media\` open. Close it and rerun. Nothing was changed. |
| `... left over from the previous run` | `source\` still existed, so this run only sorted the leftovers. Run again for a full re-sort. |
| `Source folder: KEPT` | Some moves failed. The files are in `source\`; reasons are in `files_not_moved.csv`. |
| Real photo/video in `CHECK` | Its format's signature is missing from `looks_like_media()`. Add it; the next run moves it out. |
| Folder structure lost for a file inside `SPECIAL` | It went to `CHECK` or `SPECIAL\SCREENSHOTS`, which win over `SPECIAL`. |
| A folder got flattened into `IMAGES`/`DATED`/`OTHERS` | It wasn't under `media\SPECIAL\` before the run. Rebuild it from the old paths in `index_history`. |
| Can't see dates in `IMAGES` | Names have no date. Sort by "Date modified". |
| Username cut off mid-word | It was longer than 50 characters. |
| Username `notes_txt`, `12345_jpg` | No `-` in the original name, so the whole filename is taken and `.` becomes `_`. Fixed from then on. |
| Name starts with `--` (empty username) | The original name started with `YYYY_MM_DD_HH_MM`. |
| Username `ptk__20` | Digits right before the timestamp; the regex takes the last 4 as the year. |
| A new username rule had no effect on old files | Expected: sorted files keep their username (rule 0). |
| `name-1`, `name-2` | The name was already taken, likely a true duplicate. See `existing_files.txt`. |
| Same file, two different names | Different usernames (the original names differed), or one copy is in `CHECK`. |
| Same file twice, but no `-1` | The copies are in different folders (e.g. different date folders). The counter only applies within a folder. |
| Wrong date folder | The modified time was reset by copying or editing. |
| Everything → `SPECIAL` | "special" appears in the full path, including `ROOT_DIR`. Partial words count. |
| `error_...` in a name, or in `files_not_moved.csv` | `quick_id` couldn't read the file (locked or no permission). |
| All files not moved | `source\` and `media\` are on different drives (can't happen while both are under `ROOT_DIR`). |

---

## 9. Decisions

| Decision | Why |
|---|---|
| Re-sort the whole library each run (swap `media` → `source`) | The logic changes often, so changes should apply to everything. It replaced the manual "delete S, rename T → S" routine. Renaming a folder on the same drive is instant; copying would double space and time. |
| Failed files stay in `source\`; the next run resumes | Failures can be analysed in their original place. Nothing gets mixed up. |
| Delete only empty folders (`os.rmdir`), never a folder tree | The cleanup can never delete files. |
| Username is reused from already-sorted names | A re-sort must not change names. Re-extracting from a sorted name changed some usernames (`john-doe` → `john`, empty → hash). |
| No date or time in the filename | The date always comes from the modified time anyway. The time was only there to keep copies apart, and the `-N` counter does that now. Saves 20 characters. |
| Usernames cut at 50 characters | Only whole-filename "usernames" (hex IDs, video titles) are that long; real usernames are far shorter. Applied to existing names too, once. |
| `CHECK` folder, checked by content (first bytes) | The extension check alone let empty files, macOS `._` files etc. into the library. `CHECK` wins over all rules so every suspect is in one place. |
| Dated copy of `file_index.csv` per run | Original names vanish after the first sort; this is the only way to get them back. |
| Exit cleanly when there's nothing to sort | Avoids a crash on an empty library. |
| No dry-run mode | Always run for real. |
| Duplicates kept as `-N`, not overwritten | Overwriting deleted them silently. Cost: dedupe by hand. |
| `DATED\YYYY\YYYY-MM\YYYY-MM-DD` instead of `WEEKLY\YYYY-MM-W%U` | Weeks were split at month boundaries. |
| No date parsing from the filename | The modified time is the source of truth (the old `extract_date()` was unused and removed). |
| Sampled hash, not a full hash | Speed; tested as good enough. |

**Not done on purpose:** moving the summary inside the main guard.

---

## 10. Known gaps

- The old rules comment mentions an `UNKNOWN` folder that was never built; unknown usernames get `someone`.
- Small files (4 KB or less) are fingerprinted from their first 128 B only.
- Files with unknown extensions aren't content-checked (they go to `OTHERS` as they are).
- Two runs within the same second would write the same `index_history` file name (not realistic for a real run).
- Old layout: `S\` (input) and `T\` (output) under `ROOT_DIR`. Old roots: `E:\InstCurrent`, `I:\Comparision`.
- `C:\Susi\Coded\ReelSorter\reel_sorter.py` is an older copy (weekly folders, dry run, overwrites, dated names). This project is the current one.
