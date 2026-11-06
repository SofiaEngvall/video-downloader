#!/bin/sh
# This header finds the directory of THIS script, then runs it using its local .venv
""":"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
exec "$SCRIPT_DIR/.venv/bin/python3" "$0" "$@"
"""

import argparse
import sys
import os
import subprocess
import time
import yt_dlp

class SilentLogger:
    """Passes errors straight to Python without cluttering the screen."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        raise Exception(msg)

def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        
        if total > 0:
            percent = (downloaded / total) * 100
            speed = d.get('speed', 0)
            speed_mb = speed / (1024 * 1024) if speed else 0
            
            eta = d.get('eta')
            eta_str = f"{int(eta) // 60}m {int(eta) % 60}s" if eta is not None else "Unknown"
            
            sys.stdout.write(f"\r[Downloading] {percent:.1f}% | Speed: {speed_mb:.2f} MB/s | ETA: {eta_str}\x1b[K")
            sys.stdout.flush()
            
    elif d['status'] == 'finished':
        sys.stdout.write("\n[Processing] Components downloaded. Wrapping up container...\n")
        sys.stdout.flush()

def rescue_file(filename, audio_only=False, force_part=True):
    """Stitches chunks into final format. Naming depends on if the file is a part or full."""
    part_file = filename + ".part"
    base_name, _ = os.path.splitext(filename)
    
    if not os.path.exists(part_file):
        for item in os.listdir('.'):
            if item.startswith(os.path.basename(filename)) and item.endswith('.part'):
                part_file = item
                break

    if os.path.exists(part_file):
        ext = ".mp3" if audio_only else ".mp4"
        output_file = f"{base_name}.part{ext}" if force_part else f"{base_name}{ext}"
        
        print(f"\n[Finalizing] Compiling fragments to: {output_file}")
        
        if audio_only:
            cmd = ['ffmpeg', '-y', '-i', part_file, '-vn', '-c:a', 'libmp3lame', '-q:a', '2', output_file]
        else:
            cmd = ['ffmpeg', '-y', '-i', part_file, '-c', 'copy', output_file]
            
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            print("[Success] File saved cleanly.")
            os.remove(part_file)
        except Exception as error:
            print(f"[Error] ffmpeg compilation failed: {error}")
    else:
        print("\n[Notice] No working fragment data found in path to compile.")

def get_opts_with_historical_offset(url, base_opts):
    opts = base_opts.copy()
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            meta = ydl.extract_info(url, download=False)
            stream_timestamp = meta.get('timestamp')
            
        if stream_timestamp:
            historical_struct = time.localtime(stream_timestamp)
            if time.daylight and historical_struct.tm_isdst > 0:
                offset_seconds = -time.altzone
            else:
                offset_seconds = -time.timezone
                
            sign = "+" if offset_seconds >= 0 else "-"
            offset_str = f"{sign}{abs(offset_seconds)}"
            
            opts['outtmpl'] = f'%(timestamp{offset_str}>%Y-%m-%d_%H-%M-%S)s %(uploader)s - %(title)s.%(ext)s'
            return opts, meta
    except Exception:
        pass
        
    opts['outtmpl'] = '%(timestamp>%Y-%m-%d_%H-%M-%S)s %(uploader)s - %(title)s.%(ext)s'
    return opts, None

def download_stream(url, format_selection="best", audio_only=False, interactive=True):
    """
    Exposed core function. Can be imported directly into other scripts/bots.
    Set interactive=False when running inside an automated background daemon bot.
    """
    base_opts = {
        'noplaylist': True,
        'hls_use_mpegts': True, 
        'progress_hooks': [progress_hook],
        'logger': SilentLogger(),     
        'no_warnings': True,
        'nooverwrites': True,
        'overwrites': False,
        'retries': 0,                 
        'fragment_retries': 0,        
        'skip_unavailable_fragments': False,
        'format': format_selection
    }

    if audio_only:
        base_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

    print(f"Target URL: {url}")
    print("[Connecting] Fetching original broadcast details...")
    
    ydl_opts, metadata = get_opts_with_historical_offset(url, base_opts)
    filename = None
    
    while True:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if not metadata:
                    metadata = ydl.extract_info(url, download=False)
                
                raw_filename = ydl.prepare_filename(metadata)
                base_name, _ = os.path.splitext(raw_filename)
                target_ext = ".mp3" if audio_only else ".mp4"
                filename = base_name + target_ext
                
                print(f"[File Target] Destination: {filename}")
                
                if os.path.exists(filename):
                    print("[System] Complete file already exists in directory. Skipping.")
                    return True
                
                ydl.download([url])
                
            # If running in an automated bot script, bypass manual prompt questions
            if not interactive:
                rescue_file(filename, audio_only=audio_only, force_part=True)
                return True

            # ROUTE 1: Stream closed natively. Prompt User.
            try:
                ask_complete = input("\nDownload process completed. Was the full stream recorded? [y/N]: ").strip().lower()
            except KeyboardInterrupt:
                ask_complete = 'n'
                
            if ask_complete in ['y', 'yes']:
                rescue_file(filename, audio_only=audio_only, force_part=False)
                print("[Done] Full stream saved successfully!")
            else:
                rescue_file(filename, audio_only=audio_only, force_part=True)
                print("[Done] Truncated segment saved as partial.")
            return True
            
        except KeyboardInterrupt:
            # ROUTE 2: User hit Ctrl+C manually
            print("\n[Stopped] Download cancelled by user.")
            if not interactive:
                if filename:
                    rescue_file(filename, audio_only=audio_only, force_part=True)
                return False
                
            try:
                ask_save = input("Save what has been downloaded so far? [Y/n]: ").strip().lower()
            except KeyboardInterrupt:
                ask_save = 'n'
                
            if ask_save in ['y', 'yes', '']:
                if filename:
                    rescue_file(filename, audio_only=audio_only, force_part=True)
            return False
            
        except Exception as error:
            # ROUTE 3: Initial network connection failures
            print(f"\n[Warning] Connection failure: {error}")
            if not interactive:
                time.sleep(30) # Automatic bot wait
                return False
                
            metadata = None 
            try:
                ask_retry = input("Network offline. Retry connection? [Y/n]: ").strip().lower()
            except KeyboardInterrupt:
                ask_retry = 'n'
            
            if ask_retry in ['y', 'yes', '']:
                print("[Reset] Re-attempting connection layout...")
                time.sleep(1)
                continue
            else:
                return False

def main():
    parser = argparse.ArgumentParser(description="CLI Downloader for YouTube and Twitch.")
    parser.add_argument("url", help="The YouTube or Twitch URL to download")
    
    quality = parser.add_mutually_exclusive_group()
    quality.add_argument("--best", action="store_true")
    quality.add_argument("--1080p", dest="hd", action="store_true")
    quality.add_argument("--720p", dest="sd", action="store_true")
    quality.add_argument("--audio", action="store_true")

    args = parser.parse_args()

    # Parse format flags to match library arguments
    format_selection = "bestvideo+bestaudio/best"
    if args.hd:
        format_selection = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    elif args.sd:
        format_selection = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
    elif args.audio:
        format_selection = 'bestaudio/best'

    download_stream(
        url=args.url, 
        format_selection=format_selection, 
        audio_only=args.audio, 
        interactive=True
    )

if __name__ == "__main__":
    main()
