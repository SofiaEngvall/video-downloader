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

is_finished = False

class SilentLogger:
    """Passes inner network exceptions straight to Python without terminal spam."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg):
        raise Exception(msg)

def progress_hook(d):
    global is_finished
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        
        info = d.get('info_dict', {})
        vcodec = info.get('vcodec')
        acodec = info.get('acodec')
        
        track_type = "Downloading"
        if vcodec != 'none' and acodec == 'none':
            track_type = "Downloading Video"
        elif vcodec == 'none' and acodec != 'none':
            track_type = "Downloading Audio"
        
        if total > 0:
            percent = (downloaded / total) * 100
            speed = d.get('speed', 0)
            speed_mb = speed / (1024 * 1024) if speed else 0
            
            eta = d.get('eta')
            eta_str = f"{int(eta) // 60}m {int(eta) % 60}s" if eta is not None else "Unknown"
            
            sys.stdout.write(f"\r[{track_type}] {percent:.1f}% | Speed: {speed_mb:.2f} MB/s | ETA: {eta_str}\x1b[K")
            sys.stdout.flush()
            
    elif d['status'] == 'finished':
        is_finished = True
        sys.stdout.write("\n[FFmpeg] Converting components into final media container...\n")
        sys.stdout.flush()

def rescue_file(filename, audio_only=False, force_part=True):
    """Stitches available fragments together into a marked partial or full file using ffmpeg."""
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
        cmd = ['ffmpeg', '-y', '-i', part_file, '-vn', '-c:a', 'libmp3lame', '-q:a', '2', output_file] if audio_only else ['ffmpeg', '-y', '-i', part_file, '-c', 'copy', output_file]
            
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            print("[Success] File saved cleanly.")
            os.remove(part_file)
        except Exception as error:
            print(f"[Error] ffmpeg compilation failed: {error}")
    else:
        print("\n[Notice] No working fragment data found in path to compile.")

def get_opts_with_historical_offset(url, base_opts):
    """Queries the video's stream time first to apply the user's historical timezone offset."""
    opts = base_opts.copy()
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            meta = ydl.extract_info(url, download=False)
            stream_timestamp = meta.get('timestamp')
            
        if stream_timestamp:
            historical_struct = time.localtime(stream_timestamp)
            offset_seconds = -time.altzone if (time.daylight and historical_struct.tm_isdst > 0) else -time.timezone
            sign = "+" if offset_seconds >= 0 else "-"
            opts['outtmpl'] = f'%(timestamp{sign}{abs(offset_seconds)}>%Y-%m-%d_%H-%M-%S)s %(uploader)s - %(title)s.%(ext)s'
            return opts, meta
    except Exception as error:
        raise error

def check_twitch_live_status(url):
    """Quick check to verify if a Twitch channel stream is actively transmitting online."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            meta = ydl.extract_info(url, download=False)
            return meta.get('is_live', False)
    except Exception:
        return False

def download_interactive(url, format_selection, audio_only):
    """Function exposed specifically for CLI terminal interactions with human users."""
    global is_finished
    
    opts = {
        'noplaylist': True, 'hls_use_mpegts': True, 'progress_hooks': [progress_hook],
        'logger': SilentLogger(), 'no_warnings': True, 'nooverwrites': True, 'overwrites': False,
        'retries': 0, 'fragment_retries': 0, 'skip_unavailable_fragments': False, 'format': format_selection
    }
    if audio_only:
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

    try:
        ydl_opts, metadata = get_opts_with_historical_offset(url, opts)
    except Exception as error:
        print(f"\n[Fatal Error] Unable to parse item metadata: {error}")
        return False

    filename = None
    is_true_live_stream = "twitch.tv" in url and "/videos/" not in url and "/clip/" not in url

    while True:
        try:
            is_finished = False
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if not metadata:
                    metadata = ydl.extract_info(url, download=False)
                
                raw_filename = ydl.prepare_filename(metadata)
                filename = os.path.splitext(raw_filename)[0] + (".mp3" if audio_only else ".mp4")
                
                print(f"[File Target] Destination: {filename}")
                if os.path.exists(filename):
                    print("[System] Complete file already exists in directory. Skipping.")
                    return True
                
                ydl.download([url])
            
            if is_finished:
                print("[Done] Download completed successfully!")
                return True

            if is_true_live_stream:
                print("\n[Monitor] Live feed disconnected. Monitoring channel status for reconnection...")
                reconnected = False
                for attempt in range(1, 7):
                    print(f"[Monitor] Checking status (Attempt {attempt}/6)...")
                    if check_twitch_live_status(url):
                        print("[Monitor] Streamer reconnected! Resuming...")
                        reconnected = True
                        break
                    time.sleep(30)
                if reconnected:
                    metadata = None
                    continue
            
            if is_true_live_stream:
                try:
                    ask_complete = input("\nDownload process completed. Was the full stream recorded? [y/N]: ").strip().lower()
                except KeyboardInterrupt:
                    ask_complete = 'n'
                    
                if ask_complete in ['y', 'yes']:
                    rescue_file(filename, audio_only=audio_only, force_part=False)
                else:
                    rescue_file(filename, audio_only=audio_only, force_part=True)
            else:
                raise Exception("Media stream collection cut short unexpectedly.")
            return True
            
        except KeyboardInterrupt:
            print("\n[Stopped] Download cancelled by user.")
            try:
                ask_save = input("Save what has been downloaded so far? [Y/n]: ").strip().lower()
            except KeyboardInterrupt:
                ask_save = 'n'
            if ask_save in ['y', 'yes', ''] and filename:
                rescue_file(filename, audio_only=audio_only, force_part=True)
            return False
            
        except Exception as error:
            print(f"\n[Warning] Connection failure during download track: {error}")
            metadata = None
            try:
                ask_retry = input("Network offline or connection dropped. Retry connection? [Y/n]: ").strip().lower()
            except KeyboardInterrupt:
                ask_retry = 'n'
            if ask_retry in ['y', 'yes', '']:
                continue
            else:
                return False

def download_automated(url, format_selection, audio_only, max_bot_retries=10, retry_delay_seconds=30):
    """Function exposed specifically for automated cron jobs or background daemon script loops."""
    global is_finished
    
    opts = {
        'noplaylist': True, 'hls_use_mpegts': True, 'progress_hooks': [progress_hook],
        'logger': SilentLogger(), 'no_warnings': True, 'nooverwrites': True, 'overwrites': False,
        'retries': 0, 'fragment_retries': 0, 'skip_unavailable_fragments': False, 'format': format_selection
    }
    if audio_only:
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

    try:
        ydl_opts, metadata = get_opts_with_historical_offset(url, opts)
    except Exception:
        return False

    filename = None
    bot_attempts = 0
    is_true_live_stream = "twitch.tv" in url and "/videos/" not in url and "/clip/" not in url

    while bot_attempts < max_bot_retries:
        try:
            is_finished = False
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if not metadata:
                    metadata = ydl.extract_info(url, download=False)
                
                raw_filename = ydl.prepare_filename(metadata)
                filename = os.path.splitext(raw_filename)[0] + (".mp3" if audio_only else ".mp4")
                
                if os.path.exists(filename):
                    return True
                
                ydl.download([url])
                
            if is_finished:
                return True

            if is_true_live_stream and check_twitch_live_status(url):
                metadata = None
                continue
            
            force_part_flag = is_true_live_stream and not is_finished
            if filename:
                rescue_file(filename, audio_only=audio_only, force_part=force_part_flag)
            return True
            
        except (KeyboardInterrupt, Exception):
            bot_attempts += 1
            metadata = None
            time.sleep(retry_delay_seconds)

    if filename:
        rescue_file(filename, audio_only=audio_only, force_part=True)
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

    format_selection = "bestvideo+bestaudio/best"
    if args.hd:
        format_selection = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    elif args.sd:
        format_selection = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
    elif args.audio:
        format_selection = 'bestaudio/best'

    download_interactive(args.url, format_selection, args.audio)

if __name__ == "__main__":
    main()

