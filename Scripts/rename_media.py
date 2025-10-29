#!/usr/bin/env python3

import argparse
import time
import os
import re
import sys
import shutil
import xml.etree.ElementTree as ET
from typing import List, NamedTuple
import logging

LOG_FILE = 'rename_media_service.log'

if hasattr(sys, 'ps1') or sys.flags.interactive or sys.stdin.isatty():
    logging.basicConfig(level=logging.INFO,
                        format='%(message)s')
else:
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

# A helper class to store information about files to be processed.
class FileToProcess(NamedTuple):
    original_path: str
    suffix: str

def rename_and_move_files_from_nfo(nfo_file_path: str, is_dry_run: bool):
    """
    Renames and moves media files and their accessories into a dedicated folder
    based on NFO metadata.
    """
    logging.info(f"Processing: '{nfo_file_path}'")
    try:
        directory = os.path.dirname(nfo_file_path) or "."
        original_base_name = os.path.splitext(os.path.basename(nfo_file_path))[0]

        tree = ET.parse(nfo_file_path)
        root = tree.getroot()

        if root.tag != "movie":
            logging.error("Could not find the root <movie> tag. Skipping.")
            return

        # Extract metadata from NFO
        title = root.findtext("title")
        year = root.findtext("year")
        codec = root.find(".//codec")
        width = root.find(".//width")
        height = root.find(".//height")
        tmdb_id_element = root.find(".//uniqueid[@type='tmdb']")
        tmdb_id = tmdb_id_element.text if tmdb_id_element is not None else None

        default_audio_language = root.find(".//audio[default='True']/language")
        if default_audio_language is None:
            default_audio_language = root.find(".//language")
        audio_lang = default_audio_language.text if default_audio_language is not None else None

        title = title.title() if title else ""

        if not all([title, year, codec is not None, width is not None, height is not None, audio_lang, tmdb_id]):
            logging.error("Could not find all required tags for renaming. Skipping.")
            return

        codec_text = codec.text
        width_text = width.text
        height_text = height.text

        sanitized_folder_name = sanitize_file_name(f"{title} ({year})")
        destination_directory_path = os.path.join(directory, str(year), sanitized_folder_name)

        if not is_dry_run:
            os.makedirs(destination_directory_path, exist_ok=True)
        else:
            logging.info(f"  [DRY RUN] Would ensure directory exists: '{destination_directory_path}'")

        new_base_name = sanitize_file_name(f"{title} ({year}) [tmdbid={tmdb_id}] - {width_text}x{height_text}.{codec_text.upper()}.{audio_lang.upper()}")

        files_to_process = find_associated_files(directory, original_base_name)

        if not files_to_process:
            logging.warning(f"No files found associated with base name '{original_base_name}'. Skipping.")
            return

        for file_info in files_to_process:
            file_extension = os.path.splitext(file_info.original_path)[1]
            new_base_name_with_suffix = new_base_name + file_info.suffix

            final_file_name = f"{new_base_name_with_suffix}{file_extension}"
            counter = 1
            while os.path.exists(os.path.join(destination_directory_path, final_file_name)):
                final_file_name = f"{new_base_name_with_suffix} ({counter}){file_extension}"
                counter += 1

            final_file_path = os.path.join(destination_directory_path, final_file_name)
            original_file_name = os.path.basename(file_info.original_path)

            if is_dry_run:
                logging.info(f"  [DRY RUN] Would move: '{original_file_name}'")
                logging.info(f"                    to: '{final_file_path}'")
            else:
                shutil.move(file_info.original_path, final_file_path)
                logging.info(f"Moved: '{original_file_name}' to: '{final_file_path}'")

        return True

    except Exception as ex:
        logging.error(f"An unexpected error occurred: {ex}")
    finally:
        logging.info('-' * (len(nfo_file_path) + 18))

def find_associated_files(directory: str, original_base_name: str) -> List[FileToProcess]:
    """
    Finds all files associated with a base name, including those with suffixes.
    """
    files_to_process = []
    excluded_extensions = {".mkv", ".mp4", ".nfo"}

    for file_path in os.listdir(directory):
        full_path = os.path.join(directory, file_path)
        if os.path.isfile(full_path):
            file_name_without_ext, ext = os.path.splitext(file_path)

            if file_name_without_ext.lower() == original_base_name.lower():
                files_to_process.append(FileToProcess(full_path, ""))
            elif file_name_without_ext.lower().startswith(original_base_name.lower()) and ext.lower() not in excluded_extensions:
                suffix = file_name_without_ext[len(original_base_name):]
                files_to_process.append(FileToProcess(full_path, suffix))

    return files_to_process

def sanitize_file_name(file_name: str) -> str:
    """
    Removes invalid characters from a file name.
    """
    file_name = file_name.replace(":", " -")
    invalid_chars = r'[<>:"/\\|?*]'
    return re.sub(invalid_chars, "", file_name).strip()


def monitor(monitor_dirs: list[str]):
    """
    Main function to set up and start the file system monitor.
    """

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class NFOEventHandler(FileSystemEventHandler):
       def on_created(self, event):
            if event.is_directory:
                return

            if event.src_path.lower().endswith('.nfo'):
                logging.info(f"New .nfo file detected: {event.src_path}")
                time.sleep(10)
                rename_and_move_files_from_nfo(event.src_path, is_dry_run=False)

    event_handler = None
    observer = None

    for monitor_dir in monitor_dirs:
        # Ensure the monitored directory exists
        if not os.path.isdir(monitor_dir):
            logging.error(f"Cannot monitor '{monitor_dir}'. The directory does not exist.")
            continue

        if observer is None:
            observer = Observer()

        if event_handler is None:
            event_handler = NFOEventHandler()

        observer.schedule(event_handler, path=monitor_dir, recursive=False)
        logging.info(f"Monitoring directory: '{os.path.abspath(monitor_dir)}' for new NFO files...")

    if observer is None:
        logging.error("No valid directories to monitor. Exiting.")
        return

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Monitoring stopped by user.")
    observer.join()


def main():
    parser = argparse.ArgumentParser(description="Renames and moves media files and their accessories into a dedicated folder based on NFO metadata.")
    parser.add_argument("nfo_files", nargs="*", help="One or more paths to the NFO files to be processed.")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Show what files would be renamed and moved without actually performing the actions.")
    parser.add_argument("-m", "--monitor-dirs", nargs='+',
        metavar='DIRECTORY', help="One or more directories to monitor for NFO files for automatic renaming/organization.")

    args = parser.parse_args()

    if args.monitor_dirs:
        monitor(args.monitor_dirs)
        return

    if args.dry_run:
        logging.info("\033[93m>>> DRY RUN MODE ENABLED. NO FILES WILL BE CHANGED. <<<\n\033[0m")

    proc_count = 0
    for nfo_file in args.nfo_files:
        if os.path.exists(nfo_file):
            if rename_and_move_files_from_nfo(nfo_file, args.dry_run):
                proc_count += 1
        else:
            logging.error(f"ERROR: File not found: '{nfo_file}'")

    logging.info(f'Processed {proc_count} of {len(args.nfo_files)} NFO files.')

if __name__ == "__main__":
    main()