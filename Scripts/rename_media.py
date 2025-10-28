#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import xml.etree.ElementTree as ET
from typing import List, NamedTuple

# A helper class to store information about files to be processed.
class FileToProcess(NamedTuple):
    original_path: str
    suffix: str

def rename_and_move_files_from_nfo(nfo_file_path: str, is_dry_run: bool):
    """
    Renames and moves media files and their accessories into a dedicated folder
    based on NFO metadata.
    """
    print(f"--- Processing: '{nfo_file_path}' ---")
    try:
        directory = os.path.dirname(nfo_file_path) or "."
        original_base_name = os.path.splitext(os.path.basename(nfo_file_path))[0]

        tree = ET.parse(nfo_file_path)
        root = tree.getroot()

        if root.tag != "movie":
            print("\033[91mERROR: Could not find the root <movie> tag. Skipping.\033[0m")
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
            print("\033[91mERROR: Could not find all required tags for renaming. Skipping.\033[0m")
            return

        codec_text = codec.text
        width_text = width.text
        height_text = height.text

        sanitized_folder_name = sanitize_file_name(f"{title} ({year})")
        destination_directory_path = os.path.join(directory, str(year), sanitized_folder_name)

        if not is_dry_run:
            os.makedirs(destination_directory_path, exist_ok=True)
        else:
            print(f"  [DRY RUN] Would ensure directory exists: '{destination_directory_path}'")

        new_base_name = sanitize_file_name(f"{title} ({year}) [tmdbid={tmdb_id}] - {width_text}x{height_text}.{codec_text.upper()}.{audio_lang.upper()}")

        files_to_process = find_associated_files(directory, original_base_name)

        if not files_to_process:
            print(f"\033[93mWARNING: No files found associated with base name '{original_base_name}'.\033[0m")
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
                print(f"  [DRY RUN] Would move: '{original_file_name}'")
                print(f"                    to: '{final_file_path}'")
            else:
                shutil.move(file_info.original_path, final_file_path)
                print(f"\033[92m  Moved: '{original_file_name}'\033[0m")
                print(f"     to: '{final_file_path}'")

    except Exception as ex:
        print(f"\033[91mAn unexpected error occurred: {ex}\033[0m")
    finally:
        print('-' * (len(nfo_file_path) + 18))

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

def main():
    parser = argparse.ArgumentParser(description="Renames and moves media files and their accessories into a dedicated folder based on NFO metadata.")
    parser.add_argument("nfo_files", nargs="+", help="One or more paths to the NFO files to be processed.")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Show what files would be renamed and moved without actually performing the actions.")

    args = parser.parse_args()

    if args.dry_run:
        print("\033[93m>>> DRY RUN MODE ENABLED. NO FILES WILL BE CHANGED. <<<\n\033[0m")

    for nfo_file in args.nfo_files:
        if os.path.exists(nfo_file):
            rename_and_move_files_from_nfo(nfo_file, args.dry_run)
        else:
            print(f"\033[91mERROR: File not found: '{nfo_file}'\033[0m")


if __name__ == "__main__":
    main()