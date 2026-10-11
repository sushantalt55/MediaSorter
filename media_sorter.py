import os
import csv
import re
import sys
import shutil
import hashlib
import time

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
# Root working directory containing the media, source and log folders.
ROOT_DIR = r"C:\Susi\MediaCurrent"

# Working directories relative to ROOT_DIR.
# MEDIA_DIR is the sorted library and also the drop zone for new files.
# At the start of a run it is renamed to SOURCE_DIR and re-sorted into a fresh MEDIA_DIR.
# SOURCE_DIR is removed at the end of a run once it holds no files.
MEDIA_DIR = os.path.join(ROOT_DIR, "media")
SOURCE_DIR = os.path.join(ROOT_DIR, "source")
TARGET_DIR = MEDIA_DIR
LOGS_DIR = os.path.join(ROOT_DIR, "LOGS")
# Dated copy of file_index.csv for every run.
INDEX_HISTORY_DIR = os.path.join(LOGS_DIR, "index_history")

# Ensure output directories exist.
os.makedirs(LOGS_DIR, exist_ok=True)

OUTPUT_CSV = "file_index.csv"


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".heic",".jfif"}
VIDEO_EXTENSIONS = {".mp4"}

# Usernames longer than this are cut to this length.
USERNAME_MAX_LEN = 50


# ------------------------------------------------------------------
# FILE TYPE DETECTION
# ------------------------------------------------------------------
def get_file_type(extension):
    ext = extension.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in VIDEO_EXTENSIONS:
        return "mp4"
    return None

# ------------------------------------------------------------------
# MEDIA CONTENT CHECK
# ------------------------------------------------------------------
# ISO base media box types that can open an mp4 / mov / heic / avif file.
ISO_BOX_TYPES = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}

def looks_like_media(file_path):
    # Check the first bytes of the file against known image and video signatures.
    # Any media signature is accepted for any media extension, so e.g. a webp saved
    # as .jpg still counts as media. Empty or unreadable files are suspect.
    try:
        with open(file_path, "rb", buffering=0) as f:
            head = f.read(12)
    except Exception:
        return False

    return (
        head.startswith(b"\xff\xd8\xff")                          # jpeg / jfif
        or head.startswith(b"\x89PNG\r\n\x1a\n")                  # png
        or head.startswith((b"GIF87a", b"GIF89a"))                # gif
        or head.startswith(b"BM")                                 # bmp
        or head.startswith((b"II*\x00", b"MM\x00*"))              # tiff
        or (head.startswith(b"RIFF") and head[8:12] in (b"WEBP", b"AVI "))  # webp / avi
        or head.startswith(b"\x1a\x45\xdf\xa3")                   # mkv / webm
        or head[4:8] in ISO_BOX_TYPES                             # mp4 / mov / heic
    )

def file_checks(file_path):
    # Both reads per file, so they can run together in the thread pool.
    return quick_id(file_path), looks_like_media(file_path)

# ------------------------------------------------------------------
# USERNAME SANITIZATION
# ------------------------------------------------------------------
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*.]')

def sanitize(text):
    # Replace characters that are illegal in Windows filenames with underscores.

    if text is None:
        return None

    return INVALID_FILENAME_CHARS.sub('_', text)


# Generate a fast content fingerprint.
# Only small samples from the beginning, middle and end of the file are
# hashed, making it much faster than hashing the entire file while still
# providing an excellent identifier for duplicate detection.
def quick_id(file_path):
    try:
        stat = os.stat(file_path)
        size = stat.st_size

        h = hashlib.blake2b(digest_size=6)

        with open(file_path, "rb", buffering=0) as f:

            # first 128 bytes
            h.update(f.read(128))

            if size > 4096:

                # middle
                f.seek(size // 2)
                h.update(f.read(128))

                # end
                f.seek(max(0, size - 128))
                h.update(f.read(128))

        return f"{size}--{h.hexdigest()}"

    except Exception as e:
        return f"error_{e}"

# ------------------------------------------------------------------
# EMPTY FOLDER CLEANUP
# ------------------------------------------------------------------
def remove_empty_dirs(path):
    # Bottom-up so subfolders are removed before their parents, ending with path itself.
    # os.rmdir() only removes empty folders, so files are never deleted.
    for root, dirs, files in os.walk(path, topdown=False):
        try:
            os.rmdir(root)
        except OSError:
            pass

# ------------------------------------------------------------------
# USERNAME EXTRACTION
# ------------------------------------------------------------------
# Name given by this script: username--size--hash[-N].ext
# Older runs put the time (HHMMSS--) or date and time (YYYY-MM-DD--HHMMSS--) in front;
# those names are still recognised and the prefix is dropped.
SORTED_NAME = re.compile(
    r'^(?:(?:\d{4}-\d{2}-\d{2}--)?\d{6}--)?(?P<username>.*)--\d+--[0-9a-f]{12}(?:-\d+)?(?:\.[^.]*)?$'
)

def extract_username(filename):
    """
    Extract the username from a media filename.

    Strategy
    --------
    0. If the file already has a sorted name, reuse its username unchanged.
    1. Apply a generic extraction rule that works for most filenames.
    2. Apply special-case rules for known filename formats.
       These rules intentionally override the generic result.
    3. Sanitize the extracted username before returning it.
    Every username is cut to USERNAME_MAX_LEN characters.

    Returns
    -------
    dict:
        {
            'username'   : Extracted username (or None),
            'error'      : True if extraction failed,
            'error_desc' : Reserved for future diagnostics
        }
    """

    error = True
    error_desc = None
    username = None

    # ------------------------------------------------------------------
    # Rule 0 : Already sorted
    #
    # Files sorted by an earlier run already have the name
    #     username--size--hash[-N].ext
    # (or the older HHMMSS--... and YYYY-MM-DD--HHMMSS--... forms).
    # Their username is reused as-is, so it never changes across runs.
    # No other rule is applied to them. The length cap is applied again,
    # which only shortens names sorted before the cap existed.
    #
    # Example:
    #   john_doe--5--28ff9a91f84b-1.mp4          -> john_doe
    #   143002--john_doe--5--28ff9a91f84b.mp4    -> john_doe
    # ------------------------------------------------------------------
    sorted_match = SORTED_NAME.match(filename)

    if sorted_match:
        return {
            "username": sorted_match.group("username")[:USERNAME_MAX_LEN],
            "error": False,
            "error_desc": None
        }

    # ------------------------------------------------------------------
    # Rule 1 : Generic extraction
    #
    # Split the filename on hyphens.
    # The first segment containing at least one alphabetic character
    # is assumed to be the username.
    #
    # Examples:
    #   john-doe-video.mp4          -> john
    #   abc123-xyz.mp4              -> abc123
    # ------------------------------------------------------------------
    parts = filename.split('-')

    for part in parts:
        if re.search(r'[A-Za-z]', part):
            username = part
            error = False
            break

    # ------------------------------------------------------------------
    # Special filename patterns
    #
    # These rules override the generic extraction above whenever a
    # recognised filename format is encountered.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # THREADS
    #
    # Threads downloads begin with "IMG_".
    #
    # Example:
    #   IMG_123456789.jpg
    # ------------------------------------------------------------------
    p0 = r'IMG_'
    username_match = re.match(p0, filename)

    if username_match:
        username = "Threads"
        error = False
        error_desc = None

    # ------------------------------------------------------------------
    # STANDARD TIMESTAMP FORMAT
    #
    # Extract everything preceding a timestamp of the form:
    #
    #     YYYY_MM_DD_HH_MM
    #
    # Examples:
    #   john_doe2025_06_15_14_30.mp4
    #       -> john_doe
    #
    # Tricky cases:
    #
    #   ptk__202026_03_03_15_22_xxxxx
    #       -> ptk__20
    #
    # The positive lookahead prevents the year from becoming part of
    # the username while still allowing usernames ending in digits.
    # ------------------------------------------------------------------
    p1 = r'.*(?=[\d]{4}_[\d]{2}_[\d]{2}_[\d]{2}_[\d]{2})'
    username_match = re.match(p1, filename)

    if username_match:
        username = username_match.group(0)
        error = False

    # ------------------------------------------------------------------
    # SCREENSHOTS
    #
    # Examples:
    #   Screenshot_20240731_093255_Gallery.jpg
    # ------------------------------------------------------------------
    p2 = r'Screenshot'
    username_match = re.match(p2, filename)

    if username_match:
        username = username_match.group(0)
        error = False

    # ------------------------------------------------------------------
    # TIKTOK / YOUTUBE SHORTS
    #
    # Some downloaded filenames contain the text
    # "YT and Tik". These are normalised to a single username.
    # ------------------------------------------------------------------
    p3 = r'YT and Tik'

    if re.search(p3, filename, re.IGNORECASE):
        username = "tiktok"
        error = False

    p4 = r'tik \('

    if re.search(p4, filename, re.IGNORECASE):
        username = "tiktok"
        error = False    

    p5 = r'yt \('

    if re.search(p5, filename, re.IGNORECASE):
        username = "tiktok"
        error = False      

    # ------------------------------------------------------------------
    # Reserved for future abnormal filename formats.
    #
    # Examples seen:
    #   #._100710756_854966164990976_1259835850628268032_n.jpg
    #
    # These files are currently corrected manually or deleted.
    # ------------------------------------------------------------------

    username = sanitize(username)

    if username is not None:
        username = username[:USERNAME_MAX_LEN]

    return {
        "username": username,
        "error": error,
        "error_desc": error_desc
    }
    




# ------------------------------------------------------------------
# FILE ORGANIZATION RULES
# ------------------------------------------------------------------
# Rule-1 : If the extension is image/mp4 but the content is not an image or video, move it to $TARGET_DIR/CHECK
# Rule-2 : If the path contains 'SPECIAL', then this goes to $TARGET_DIR/SPECIAL and path upto filename is maintained.
# Rule-3 : If the filetype is image, it goes under $TARGET_DIR/IMAGES, and relative path is not maintained.
# If filetype is mp4, move it to $TARGET_DIR/DATED/YYYY/YYYY-MM/YYYY-MM-DD. Relative path is not maintained in this case.
# Rule-4 : If the filetype is not identified, move it to $TARGET_DIR/OTHERS
# Rule-5 : if name contains 'SCREENSHOTS', in any case, move it to $TARGET_DIR/SPECIAL/SCREENSHOTS
# if username is not identified, move it to $TARGET_DIR/UNKNOWN

# Based on above rules, evaluation and putting data in csv file, with additinal columns for new file path, new file name.


# ------------------------------------------------------------------
# MAIN PROCESSING
# ------------------------------------------------------------------
if __name__ == "__main__":
    run_stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # Turn the library into the source of this run.
    # If SOURCE_DIR still exists, the previous run left files behind: sort those
    # into MEDIA_DIR instead (resume) and leave MEDIA_DIR as it is.
    if os.path.exists(SOURCE_DIR):
        print(f"'{SOURCE_DIR}' left over from the previous run. Sorting its files into '{MEDIA_DIR}'.")
    elif os.path.isdir(MEDIA_DIR):
        try:
            os.rename(MEDIA_DIR, SOURCE_DIR)
        except OSError as e:
            # Windows refuses while any file or folder inside MEDIA_DIR is open. Nothing has changed yet.
            print(f"Cannot rename '{MEDIA_DIR}' to '{SOURCE_DIR}': {e}")
            print("Close any program, Explorer window or terminal using it, then run again.")
            sys.exit(1)
    else:
        print(f"Nothing to sort: '{MEDIA_DIR}' does not exist.")
        sys.exit(0)
    os.makedirs(TARGET_DIR, exist_ok=True)

    # Collect all source files before starting parallel hashing.
    all_files = []

    for root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            all_files.append(file_path)

    total_file_count = len(all_files)
    print(f"Total files: {total_file_count}")

    if total_file_count == 0:
        remove_empty_dirs(SOURCE_DIR)
        print("Nothing to sort: no files found.")
        sys.exit(0)


    # Generate quick IDs and media checks in parallel to minimize I/O wait time.
    quick_id_results = {}
    media_ok_results = {}
    start_time=time.time()
    with ThreadPoolExecutor(max_workers=24) as executor:

        future_map = {
            executor.submit(file_checks, file_path): file_path
            for file_path in all_files
        }

        for i, future in enumerate(as_completed(future_map), 1):

            file_path = future_map[future]

            try:
                quick_id_results[file_path], media_ok_results[file_path] = future.result()

            except Exception as e:
                quick_id_results[file_path] = f"error_{e}"
                media_ok_results[file_path] = False

            if i % 100 == 0:
                print(f"\rHashed {i} files {(i/len(all_files)*100):.2f}%", end="")

        print(f"\rHashed {len(all_files)} files (100.00%)")
        hash_finish_time=time.time()
        print(f'Hashing Time:{hash_finish_time-start_time}')
             

    username_error_files=[]
    records = []
    processed_count=0
    temp_files=[]
    files_not_moved=[]
    
    moved_count=0
    check_count=0
    existed_files=[]
    existed_files_count=0
    new_files_count=0


    for root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            processed_count+=1
            # if processed_count > 10000:
            #     break

            record = {
                "file_path": None,  
                "file_type": None,
                "date": None,
                "username": None,
                "quick_id": None,
                "new_file_name": None,
                "new_file_path": None,
                "moved": False,
                "error_desc": None,
            }

           

            file_path = os.path.join(root, file)
            _, ext = os.path.splitext(file)

            file_type = get_file_type(ext)
            if not file_type:
                file_type = "unknown"
                # Unknown file type. Route it to OTHERS and record it for later review.
                temp_files.append(file_path)

            # Get the file modified date, if it is not present, use the present date.
            stat = os.stat(file_path)
            dt_obj = datetime.fromtimestamp(stat.st_mtime)

            date = dt_obj.strftime("%Y-%m-%d")

            username_info = extract_username(file)
            if username_info['error']:
                username_info['username']="someone"
                username_info['error']=False
                username_error_files.append({"file": file, "error_desc": username_info['error_desc']})

            
            record["file_path"] = file_path
            record["file_type"] = file_type     
            record["date"] = date
            record["username"] = username_info['username']  
            record["error_desc"] = username_info['error_desc'] or ""
            records.append(record)

            record['quick_id'] = quick_id_results[file_path]


            #-------- new fields----------------
            # get new file name as per rule: name--quickid.ext
            # No date or time in the name: the date is always read from the modified time,
            # and copies of the same file are kept apart by the -N counter.
            # Append the quick ID to make the filename content-aware.
            new_file_name = (
                f"{record['username']}"
                f"--{record['quick_id']}{ext}"
            )
            record["new_file_name"] = new_file_name
            # get new file path as per rules
            if file_type != "unknown" and not media_ok_results[file_path]:
                # Media extension, but the content does not look like an image or video
                # (empty file, metadata file, wrong extension...). Kept apart for review.
                new_file_path = os.path.join(TARGET_DIR, "CHECK")
                check_count += 1
            elif "SCREENSHOT" in file.upper():
                new_file_path = os.path.join(TARGET_DIR, "SPECIAL", "SCREENSHOTS")
            elif "SPECIAL" in root.upper():
                # Preserve the directory structure beginning after the last
                # occurrence of "SPECIAL" in the source path.
                special_index = root.upper().rfind("SPECIAL")
                relative_path = root[special_index + len("SPECIAL"):].lstrip("\\/")
                new_file_path = os.path.join(TARGET_DIR, "SPECIAL", relative_path)
            elif file_type == "image":
                new_file_path = os.path.join(TARGET_DIR, "IMAGES")
            elif file_type == "mp4":
                # To be put into a date folder nested inside its month and year: DATED/YYYY/YYYY-MM/YYYY-MM-DD.
                # Relative path not to be maintained in this case.
                new_file_path = os.path.join(
                    TARGET_DIR,
                    "DATED",
                    dt_obj.strftime("%Y"),
                    dt_obj.strftime("%Y-%m"),
                    dt_obj.strftime("%Y-%m-%d"),
                )

            else:
                # move to OTHERS without relative path maintained.
                new_file_path = os.path.join(TARGET_DIR, "OTHERS")

            record["new_file_path"] = new_file_path

            # Count existing files and new files for stats.
            new_full_path = os.path.join(new_file_path, new_file_name)
            if os.path.exists(new_full_path):
                existed_files_count += 1
                existed_files.append(new_full_path)

                # Keep the duplicate: append -1, -2, -3 ... to the name until it is free.
                name_stem, name_ext = os.path.splitext(new_file_name)
                suffix = 1
                while os.path.exists(new_full_path):
                    new_file_name = f"{name_stem}-{suffix}{name_ext}"
                    new_full_path = os.path.join(new_file_path, new_file_name)
                    suffix += 1
                record["new_file_name"] = new_file_name
            else:
                new_files_count += 1

            #---------------Moving the files------------------------------------
            os.makedirs(new_file_path, exist_ok=True)
            try:
                # os.rename() fails instead of overwriting if the destination exists.
                os.rename(file_path, new_full_path)
                record["moved"] = True
                moved_count += 1
            except Exception as e:
                files_not_moved.append({"file": file_path, "error_desc": str(e)})
                record["moved"] = False
            # display progress every 100 files
            if processed_count % 100 == 0:
                print(f"\rProcessed {processed_count} files ({processed_count/total_file_count*100:.2f}%)", end="")
    print(f"\rProcessed {processed_count} files ({processed_count/total_file_count*100:.2f}%)", end="")
    finish_time=time.time()
    print(f'\nProcessing Time:{finish_time-hash_finish_time}')
#-----------------------------------------------------------------------------
    # Create directory LOGS for putting the csv files. If it already exists, it will not throw error.
    # Write the complete processing index.
    with open(os.path.join(LOGS_DIR, OUTPUT_CSV), "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["file_path", "file_type", "date", "username", "quick_id", "new_file_name", "new_file_path", "moved", "error_desc"]    
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    # Keep a dated copy so original names of every run stay recoverable.
    os.makedirs(INDEX_HISTORY_DIR, exist_ok=True)
    shutil.copy2(
        os.path.join(LOGS_DIR, OUTPUT_CSV),
        os.path.join(INDEX_HISTORY_DIR, f"file_index_{run_stamp}.csv"),
    )

      # Then write the error files to separate csv files for better analysis in the LOGS_DIR.
    with open(os.path.join(LOGS_DIR, "username_errors.csv"), "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["file", "error_desc"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for error in username_error_files:
            writer.writerow(error)        

    # Dump the temp files for review
    with open(os.path.join(LOGS_DIR, "temp_files.txt"), "w", encoding="utf-8") as f:
         for temp_file in temp_files:        
             f.write(f"{temp_file}\n")

    # Dump the existing files for review
    with open(os.path.join(LOGS_DIR, "existing_files.txt"), "w", encoding="utf-8") as f:
         for file in existed_files:        
             f.write(f"{file}\n")
    
    # Dump the files not moved for review
    with open(os.path.join(LOGS_DIR, "files_not_moved.csv"), "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["file", "error_desc"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for error in files_not_moved:
            writer.writerow(error)

    # Remove the emptied source. Folders that still hold files are kept for review.
    remove_empty_dirs(SOURCE_DIR)
    source_kept = os.path.exists(SOURCE_DIR)


# Display result
# print a newline
run_logs=[]
# Separator line for the run summary.
# print a newline
print()
run_logs.append("-" * 50)
# print Date and time of run, also root directory.
run_logs.append(f"Run Date and Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
run_logs.append(f"Source Directory: {SOURCE_DIR}")
run_logs.append(f"Total files: {total_file_count}")
run_logs.append(f"Records written: {len(records)}")
run_logs.append(f"Username extraction errors: {len(username_error_files)}")
run_logs.append(f"Files moved: {moved_count}")
run_logs.append(f"Files not moved: {len(files_not_moved)}")
run_logs.append(f"Existed files: {existed_files_count}")
run_logs.append(f"New files: {new_files_count}")
run_logs.append(f"Suspected non-media (CHECK): {check_count}")
run_logs.append(f"Source folder: {'KEPT - files left in it, see files_not_moved.csv' if source_kept else 'removed (empty)'}")
# insert another dashline
run_logs.append("-" * 50)
# Append to the run_logs text file. Create the file if it does not exist, else append to it. Each run should be appended as a new line in the file.
with open(os.path.join(LOGS_DIR, "run_logs.txt"), "a", encoding="utf-8") as f:
    for log in run_logs:
        f.write(f"{log}\n")
for log in run_logs:
    print(log)

