import os
import json
import tempfile
import time
import yt_dlp
from googleapiclient.discovery import build
import replicate
from replicate.exceptions import ReplicateError
from googleapiclient.errors import HttpError
from google import genai  
from google.genai import types
import logging
import sys
from dotenv import load_dotenv
import re # Added for sanitizing filenames
from google.api_core import exceptions as google_api_core_exceptions
import base64
import requests
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
import math




load_dotenv()

# --- Configuration ----
API_KEY = os.environ.get('YOUTUBE_API_KEY')
PLAYLIST_ID = os.environ.get('YOUTUBE_PLAYLIST_ID')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
REPLICATE_API_TOKEN = os.environ.get('REPLICATE_API_TOKEN')
# Directory to store the JSON data. '.' means current directory.
# On Render (Free Tier), this is ephemeral storage!
DATA_DIR = os.environ.get('DATA_DIR', 'Generated')

# --- Model Definitions ---
PRIMARY_WHISPER_MODEL = "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
FALLBACK_WHISPERX_MODEL = "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"

# --- Gemini Model Configuration ---
# Use the new experimental model as primary, flash as fallback
PRIMARY_GEMINI_MODEL = "gemini-2.5-pro-exp-03-25"
FALLBACK_GEMINI_MODEL = "gemini-2.0-flash"

# --- Constants ---
STATE_FILE = os.path.join(DATA_DIR, 'playlist_state.json') # Keep state file in data dir too
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
MAX_RESULTS_PER_FETCH = 50
REPLICATE_WHISPER_MODEL = "vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
# --- JSON Filename Template (will be adapted per category) ---
JSON_FILENAME_PREFIX = ""

# --- Configuration ----
ANKI_CONNECT_URL = os.environ.get('ANKI_CONNECT_URL', 'http://127.0.0.1:8765')
# --- ANKI CONFIGURATION (USER MUST VERIFY THESE MATCH THEIR ANKI SETUP) ---
ANKI_DEFAULT_DECK_NAME = os.environ.get('ANKI_DEFAULT_DECK_NAME', 'Generated::YouTube Flashcards') # Default deck if Gemini doesn't provide one
ANKI_NOTE_TYPE = os.environ.get('ANKI_NOTE_TYPE', 'Basic') # The exact name of the Anki Note Type to use
ANKI_FIELD_FRONT = os.environ.get('ANKI_FIELD_FRONT', 'Front') # The exact name of the field for the question/front
ANKI_FIELD_BACK = os.environ.get('ANKI_FIELD_BACK', 'Back')   # The exact name of the field for the answer/back
ANKI_FIELD_SOURCE = os.environ.get('ANKI_FIELD_SOURCE') # Optional: Field name to store video title/URL
ANKI_TAGS_FROM_CATEGORY = os.environ.get('ANKI_TAGS_FROM_CATEGORY', 'true').lower() == 'true' # Use Gemini category as tag?

# --- Logging Setup ---
# --- Logging Setup ---
# Define log file path within the DATA_DIR
LOG_FILENAME = 'youtube_flashcard_script.log'
LOG_FILEPATH = os.path.join(DATA_DIR, LOG_FILENAME)

# Ensure the directory for the log file exists before setting up logging
try:
    # Use os.path.dirname to get the directory part of the path
    log_dir = os.path.dirname(LOG_FILEPATH)
    if log_dir: # Ensure log_dir is not empty (e.g., if DATA_DIR is '.')
         os.makedirs(log_dir, exist_ok=True)
except OSError as e:
    # If we can't create the directory, we can't log to file.
    # Print an error to stderr and fall back to basic console logging.
    print(f"CRITICAL ERROR: Could not create log directory {log_dir}: {e}. File logging disabled.", file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # Add a log record about the failure after basicConfig is set
    logging.critical(f"Failed to create log directory {log_dir}. File logging disabled.")
    # Depending on severity, you might want to sys.exit(1) here
else:
    # If directory exists or was created, proceed with detailed logging setup
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # Set the minimum level for the logger

    # --- File Handler ---
    # Use 'a' mode for appending to the log file each run
    try:
        file_handler = logging.FileHandler(LOG_FILEPATH, mode='a', encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.INFO) # Log INFO level and above to the file
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Handle potential errors opening the file (e.g., permissions)
        print(f"ERROR: Could not set up file logging handler for {LOG_FILEPATH}: {e}. File logging disabled.", file=sys.stderr)
        # Fall back to basic console logging if file handler fails
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.error(f"Failed to configure file logging handler for {LOG_FILEPATH}. File logging disabled.")
    else:
        # --- Console Handler (only add if file handler succeeded or wasn't attempted due to dir error) ---
        # We still want console output even if file logging setup had an issue,
        # unless basicConfig already took over. Check if basicConfig was used.
        if not isinstance(root_logger.handlers[0], logging.StreamHandler) or len(root_logger.handlers) > 1:
             # Add console handler only if basicConfig didn't already set one up
             # or if we successfully added the file handler.
            console_handler = logging.StreamHandler(sys.stdout) # Log to standard output
            console_handler.setFormatter(log_formatter)
            console_handler.setLevel(logging.INFO) # Log INFO level and above to the console
            root_logger.addHandler(console_handler)
            logging.info(f"Logging configured. Console: INFO+, File: {LOG_FILEPATH} (INFO+)")
        elif len(root_logger.handlers) == 1 and isinstance(root_logger.handlers[0], logging.FileHandler):
             # Edge case: File handler added, but basicConfig wasn't called, and we need console too.
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(log_formatter)
            console_handler.setLevel(logging.INFO)
            root_logger.addHandler(console_handler)
            logging.info(f"Logging configured. Console: INFO+, File: {LOG_FILEPATH} (INFO+)")

# --- Helper Functions ---

def sanitize_filename(name):
    """Removes potentially problematic characters for filenames."""
    # Remove leading/trailing whitespace
    name = name.strip()
    # Replace spaces and problematic characters with underscores
    name = re.sub(r'[\\/*?:"<>|\s]+', '_', name)
    # Remove any characters that are not alphanumeric, underscore, or hyphen
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    # Limit length (optional)
    # name = name[:100]
    if not name: # Handle empty names after sanitizing
        name = "default_category"
    return name

# --- (load_seen_videos, save_seen_videos, get_youtube_service, fetch_playlist_videos, is_age_restricted, download_audio, get_transcript_replicate remain the same) ---
def load_seen_videos(filename):
    """Loads the set of seen video IDs from the state file."""
    try:
        # Ensure DATA_DIR exists before trying to read
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        logging.warning(f"State file '{filename}' not found. Assuming no videos seen yet.")
        return set()
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from '{filename}'. Starting fresh.")
        return set()
    except Exception as e:
        logging.error(f"Error loading state file '{filename}': {e}")
        return set()

def save_seen_videos(filename, video_ids):
    """Saves the current set of video IDs to the state file."""
    try:
        # Ensure DATA_DIR exists before trying to write
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(list(video_ids), f, indent=4)
        logging.info(f"Successfully saved state to '{filename}'")
    except Exception as e:
        logging.error(f"Error saving state file '{filename}': {e}")

def get_youtube_service():
    if not API_KEY:
        logging.error("YOUTUBE_API_KEY environment variable not set.")
        return None
    try:
        return build(API_SERVICE_NAME, API_VERSION, developerKey=API_KEY)
    except Exception as e:
        logging.error(f"Error building YouTube service: {e}")
        return None

def fetch_playlist_videos(youtube_service, playlist_id):
    if not playlist_id:
        logging.error("YOUTUBE_PLAYLIST_ID environment variable not set.")
        return {}
    if not youtube_service:
        logging.error("YouTube service object is not available.")
        return {}
    current_videos = {}
    try:
        request = youtube_service.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=MAX_RESULTS_PER_FETCH)
        response = request.execute()
        # TODO: Add pagination logic if playlists might exceed MAX_RESULTS_PER_FETCH
        for item in response.get('items', []):
            video_id = item.get('snippet', {}).get('resourceId', {}).get('videoId')
            video_title = item.get('snippet', {}).get('title')
            if video_id and video_title:
                current_videos[video_id] = video_title
        logging.info(f"Fetched {len(current_videos)} videos from playlist {playlist_id}")
        return current_videos
    except HttpError as e:
        logging.error(f"An HTTP error {e.resp.status} occurred fetching playlist items: {e.content}")
        return {}
    except Exception as e:
        logging.error(f"An unexpected error occurred fetching playlist items: {e}")
        return {}

def is_age_restricted(youtube_service, video_id):
    if not youtube_service: return True
    try:
        video_request = youtube_service.videos().list(part="contentDetails", id=video_id)
        video_response = video_request.execute()
        items = video_response.get('items', [])
        if not items: return True
        content_details = items[0].get('contentDetails', {})
        yt_rating = content_details.get('contentRating', {}).get('ytRating')
        is_restricted = yt_rating == 'ytAgeRestricted'
        logging.info(f"Video {video_id} age restricted: {is_restricted}")
        return is_restricted
    except HttpError as e:
        logging.error(f"HTTP error checking age restriction for {video_id}: {e.content}")
        return True
    except Exception as e:
        logging.error(f"Unexpected error checking age restriction for {video_id}: {e}")
        return True

def download_audio(video_url, output_dir):
    audio_file_path = None
    # Define the path to your cookie file. Assuming it's in the same directory as the script.
    cookie_file_path = 'cookies.txt'

    try:
        # Generate a unique base filename for the temporary download
        temp_base = os.path.join(output_dir, f"ytaudio_{int(time.time())}_{os.urandom(4).hex()}")
        logging.info(f"Attempting to download audio for {video_url} to base path: {temp_base}")

        # --- yt-dlp Options ---
        # --- yt-dlp Options ---
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{temp_base}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
                'nopostoverwrites': False,
            }],
            'prefer_ffmpeg': True,
            'keepvideo': False,
            # 'quiet': True,        # <--- COMMENT OUT for debugging
            # 'no_warnings': True,  # <--- COMMENT OUT for debugging
            'verbose': True,      # <--- ADD for debugging
            'noplaylist': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
            # 'nocheckcertificate': True,
        }

        # --- Add Cookie File Option ---
        if os.path.exists(cookie_file_path):
            logging.info(f"Using cookie file: {cookie_file_path}")
            ydl_opts['cookiefile'] = cookie_file_path
            # --- OPTIONAL: Try using cookies directly from browser ---
            # If yt-dlp runs on the same machine & user context as your logged-in browser,
            # this *might* be more reliable than exported files. Uncomment *one* line below.
            # ydl_opts['cookiesfrombrowser'] = ('chrome',) # Or 'firefox', 'edge', 'opera', 'vivaldi', etc.
            # ydl_opts['cookiesfrombrowser'] = ('chrome', None, 'Default') # Example specifying profile if needed
        else:
            logging.warning(f"Cookie file not found at '{cookie_file_path}'. Proceeding without cookies...")

        final_audio_path = f"{temp_base}.mp3" # Define the expected final path AFTER conversion

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Starting yt-dlp download for {video_url}")
            # Use download method which handles postprocessing
            error_code = ydl.download([video_url])

            if error_code == 0:
                # Check if the expected MP3 file exists after download and postprocessing
                if os.path.exists(final_audio_path) and os.path.getsize(final_audio_path) > 0:
                    audio_file_path = final_audio_path
                    logging.info(f"Successfully downloaded and converted audio to {audio_file_path}")
                    return audio_file_path
                else:
                    # Sometimes the downloaded file might have a different extension temporarily
                    # before conversion, or conversion failed silently.
                    logging.error(f"yt-dlp reported success (error code 0), but the final audio file '{final_audio_path}' is missing or empty.")
                    # Check for other possible output files (e.g., .webm, .m4a) if needed for debugging
                    found_alternative = False
                    for ext in ['.webm', '.m4a', '.ogg', '.opus']: # Common audio formats yt-dlp might download
                         alt_path = f"{temp_base}{ext}"
                         if os.path.exists(alt_path):
                              logging.warning(f"Found intermediate file {alt_path}, but MP3 conversion likely failed.")
                              # Optionally try to manually convert here, or just report failure
                              found_alternative = True
                              break
                    if not found_alternative:
                        logging.error("No intermediate or final audio file found.")
                    return None
            else:
                 logging.error(f"yt-dlp download failed for {video_url} with error code {error_code}.")
                 return None

    except yt_dlp.utils.DownloadError as e:
        # Specific yt-dlp download errors (like unavailable video, network issues during download)
        logging.error(f"yt-dlp download error for {video_url}: {e}")
        # Clean up potentially partially downloaded files
        if os.path.exists(f"{temp_base}.mp3.part"): os.remove(f"{temp_base}.mp3.part")
        return None
    except Exception as e:
        # Catch other unexpected errors (like issues initializing yt-dlp, filesystem errors)
        logging.error(f"Unexpected error during audio download process for {video_url}: {e}", exc_info=True) # Log traceback
        # Clean up potentially partially downloaded files
        if os.path.exists(f"{temp_base}.mp3.part"): os.remove(f"{temp_base}.mp3.part")
        return None
    finally:
         # Optional: Clean up any leftover intermediate files if the final mp3 wasn't created
         # This is a bit tricky as yt-dlp *should* clean them, but just in case.
         # Be careful not to delete the final mp3 if it *was* created.
         pass


def _parse_replicate_output(output, model_name):
    """Tries to extract transcript from various possible Replicate output structures."""
    if not output:
        logging.warning(f"Received empty output from Replicate model {model_name}.")
        return None

    transcript = None
    if isinstance(output, dict):
        # Try common keys first
        transcript = output.get('transcription')
        if transcript:
             logging.info(f"Extracted 'transcription' key from {model_name}.")
             return transcript.strip()

        transcript = output.get('text')
        if transcript:
             logging.info(f"Extracted 'text' key from {model_name}.")
             return transcript.strip()

        # Check for whisperx specific output structure if needed (based on its actual output)
        # Example: maybe it's in output['output']['transcription']? Adjust as necessary.
        # if model_name == FALLBACK_WHISPERX_MODEL and 'output' in output and 'transcription' in output['output']:
        #     transcript = output['output']['transcription']
        #     if transcript:
        #          logging.info(f"Extracted ['output']['transcription'] key from {model_name}.")
        #          return transcript.strip()

        # Fallback to segments if primary keys fail

        segments = output.get('segments')
        if isinstance(segments, list):
            transcript = " ".join([seg.get('text', '').strip() for seg in segments]).strip()
            if transcript:
                logging.info(f"Extracted transcript from 'segments' key for {model_name}.")
                return transcript
            else:
                 logging.warning(f"Found 'segments' key for {model_name}, but it yielded an empty transcript.")

        # If still no transcript, log the whole output for debugging
        logging.warning(f"Could not find standard transcript keys ('transcription', 'text', 'segments' with text) in output from {model_name}. Full output: {output}")
        return None

    elif isinstance(output, str):
        logging.info(f"Replicate model {model_name} returned a raw string transcript.")
        return output.strip()
    else:
        logging.error(f"Unexpected output format from Replicate model {model_name}: {type(output)}. Output: {output}")
        return None

def _run_replicate_on_chunk(audio_chunk_path, attempt_num):
    """Runs Replicate transcription on a single audio chunk path with fallback."""
    transcript_chunk = None
    start_time_chunk = time.time()

    # Attempt 1: Primary Model
    logging.info(f"[Chunk Attempt {attempt_num}] Transcribing chunk {os.path.basename(audio_chunk_path)} with primary model: {PRIMARY_WHISPER_MODEL}")
    try:
        with open(audio_chunk_path, "rb") as audio_file_chunk:
            primary_input = {
                "task": "transcribe",
                "audio": audio_file_chunk,
                "language": "None",
                "timestamp": "chunk", # Keep chunk for segments if needed later
                "batch_size": 64,
                "diarise_audio": False
            }
            # Add a timeout to the replicate run call (e.g., 10 minutes = 600 seconds)
            # Note: replicate.run doesn't directly support timeout, but you can wrap it or use async with timeout
            # For simplicity here, we rely on underlying HTTP timeouts or Replicate's own limits.
            # Consider using replicate.predictions.create() and polling for more control if needed.
            output = replicate.run(PRIMARY_WHISPER_MODEL, input=primary_input)

        logging.info(f"[Chunk Attempt {attempt_num}] Primary model response received after {time.time() - start_time_chunk:.2f}s.")
        transcript_chunk = _parse_replicate_output(output, PRIMARY_WHISPER_MODEL)
        if transcript_chunk:
             logging.info(f"[Chunk Attempt {attempt_num}] Successfully transcribed chunk with primary model.")
             return transcript_chunk
        else:
             logging.warning(f"[Chunk Attempt {attempt_num}] Primary model ran but yielded no transcript for chunk.")

    except ReplicateError as e:
        # Check specifically for 413 or other informative errors if possible
        logging.warning(f"[Chunk Attempt {attempt_num}] Primary model ({PRIMARY_WHISPER_MODEL}) failed for chunk: {e}. Trying fallback.")
    except Exception as e:
        logging.warning(f"[Chunk Attempt {attempt_num}] Unexpected error with primary model for chunk: {e}. Trying fallback.", exc_info=True)


    # Attempt 2: Fallback Model (only if primary failed)
    if transcript_chunk is None:
        logging.info(f"[Chunk Attempt {attempt_num}] Attempting fallback model for chunk: {FALLBACK_WHISPERX_MODEL}")
        fallback_start_time = time.time()
        try:
            with open(audio_chunk_path, "rb") as audio_file_chunk:
                fallback_input = {
                    # Ensure the key is correct for whisperx ('audio_file'?)
                    "audio_file": audio_file_chunk,
                    "debug": False,
                    "batch_size": 64, # Adjust if needed for whisperx
                    "diarization": False,
                    # Add other whisperx specific params if needed
                }
                # Again, consider timeout mechanisms if runs are very long
                output = replicate.run(FALLBACK_WHISPERX_MODEL, input=fallback_input)

            logging.info(f"[Chunk Attempt {attempt_num}] Fallback model response received after {time.time() - fallback_start_time:.2f}s.")
            transcript_chunk = _parse_replicate_output(output, FALLBACK_WHISPERX_MODEL)
            if transcript_chunk:
                 logging.info(f"[Chunk Attempt {attempt_num}] Successfully transcribed chunk with fallback model.")
                 return transcript_chunk
            else:
                 logging.error(f"[Chunk Attempt {attempt_num}] Fallback model ran but yielded no transcript for chunk.")
                 return None # Failed for this chunk

        except ReplicateError as e:
            logging.error(f"[Chunk Attempt {attempt_num}] Fallback model ({FALLBACK_WHISPERX_MODEL}) also failed for chunk: {e}")
            return None
        except Exception as e:
            logging.error(f"[Chunk Attempt {attempt_num}] Unexpected error with fallback model for chunk: {e}", exc_info=True)
            return None

    return transcript_chunk # Return whatever we got (potentially None)


    # --- MODIFIED FUNCTION with Fallback ---
def get_transcript_replicate(audio_file_path):
    """
    Gets transcript from an audio file using Replicate's Whisper model,
    splitting the audio into chunks if it's too large, with fallback logic per chunk.
    """
    if not REPLICATE_API_TOKEN:
        logging.error("REPLICATE_API_TOKEN not configured.")
        return None
    if not os.path.exists(audio_file_path):
        logging.error(f"Audio file not found at {audio_file_path}")
        return None

    # --- Configuration for Splitting ---
    # Max chunk size in MB (adjust based on observed Replicate limits, maybe 20-24MB)
    MAX_CHUNK_SIZE_MB = 20
    CHUNK_OVERLAP_MS = 5000 # 5 seconds overlap to help catch words split at boundaries

    file_size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
    logging.info(f"Audio file size: {file_size_mb:.2f} MB")

    if file_size_mb <= MAX_CHUNK_SIZE_MB:
        # File is small enough, process directly
        logging.info("Audio file size is within limit, processing directly.")
        # Use the single chunk helper for consistency in fallback logic
        full_transcript = _run_replicate_on_chunk(audio_file_path, attempt_num=1)
        return full_transcript # May be None if transcription fails
    else:
        # File is too large, split it
        logging.info(f"Audio file size exceeds {MAX_CHUNK_SIZE_MB} MB. Splitting into chunks.")
        all_transcripts = []
        temp_chunk_dir = os.path.join(os.path.dirname(audio_file_path), "audio_chunks")
        os.makedirs(temp_chunk_dir, exist_ok=True)

        try:
            logging.info("Loading audio file with pydub...")
            audio = AudioSegment.from_mp3(audio_file_path)
            duration_ms = len(audio)
            logging.info(f"Audio duration: {duration_ms / 1000:.2f} seconds")

            # Estimate chunk duration based on size (approximate)
            # bitrate = (file_size_mb * 1024 * 1024 * 8) / (duration_ms / 1000) # bits/sec
            # max_duration_ms = (MAX_CHUNK_SIZE_MB * 1024 * 1024 * 8) / bitrate * 1000 if bitrate > 0 else duration_ms
            # Simpler: Aim for chunks of roughly 15-20 minutes if splitting
            target_chunk_duration_ms = 15 * 60 * 1000 # 15 minutes

            num_chunks = math.ceil(duration_ms / target_chunk_duration_ms)
            if num_chunks <= 1: # Should not happen if file_size_mb > MAX_CHUNK_SIZE_MB, but safety check
                 num_chunks = 2 # Force at least two chunks if splitting is triggered

            # Calculate actual chunk length based on desired number of chunks
            # This distributes the audio more evenly than a fixed duration target
            actual_chunk_len_ms = math.ceil(duration_ms / num_chunks)

            logging.info(f"Splitting into {num_chunks} chunks of approx {actual_chunk_len_ms / 1000 / 60:.1f} minutes each.")

            for i in range(num_chunks):
                start_ms = max(0, i * actual_chunk_len_ms - (CHUNK_OVERLAP_MS if i > 0 else 0) ) # Apply overlap after first chunk
                end_ms = min(duration_ms, (i + 1) * actual_chunk_len_ms)
                logging.info(f"Processing chunk {i+1}/{num_chunks} ({start_ms/1000:.1f}s to {end_ms/1000:.1f}s)")

                chunk = audio[start_ms:end_ms]
                chunk_filename = f"chunk_{i+1:03d}.mp3"
                chunk_filepath = os.path.join(temp_chunk_dir, chunk_filename)

                try:
                    logging.info(f"Exporting chunk {i+1} to {chunk_filepath}")
                    chunk.export(chunk_filepath, format="mp3", bitrate="128k") # Ensure bitrate consistency
                except Exception as export_err:
                    logging.error(f"Error exporting chunk {i+1}: {export_err}")
                    # Decide how to handle: skip chunk? fail all?
                    # For now, log and continue, resulting transcript will be partial.
                    continue # Skip to next chunk

                # Check chunk size before sending (optional sanity check)
                chunk_size_mb = os.path.getsize(chunk_filepath) / (1024 * 1024)
                if chunk_size_mb > MAX_CHUNK_SIZE_MB * 1.1: # Allow slight overrun
                     logging.warning(f"Chunk {i+1} size ({chunk_size_mb:.2f} MB) still exceeds limit slightly. Problems may occur.")

                # Transcribe the individual chunk
                transcript_piece = _run_replicate_on_chunk(chunk_filepath, attempt_num=i+1)

                if transcript_piece:
                    all_transcripts.append(transcript_piece)
                else:
                    logging.warning(f"Transcription failed for chunk {i+1}. Transcript will be incomplete.")
                    # Optionally: add a placeholder? "[TRANSCRIPTION FAILED FOR CHUNK]"
                    # all_transcripts.append("[TRANSCRIPTION FAILED]") # Or just skip

                # Clean up the individual chunk file immediately
                try:
                    os.remove(chunk_filepath)
                    # logging.debug(f"Removed temp chunk: {chunk_filepath}")
                except OSError as e:
                    logging.error(f"Error removing temp chunk {chunk_filepath}: {e}")

            # Combine transcripts
            final_transcript = " ".join(all_transcripts).strip()
            logging.info("Finished processing all chunks.")
            return final_transcript if final_transcript else None

        except CouldntDecodeError:
            logging.error(f"Pydub could not decode the audio file: {audio_file_path}. Is ffmpeg installed and accessible?", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"An error occurred during audio splitting: {e}", exc_info=True)
            return None
        finally:
            # Clean up the chunk directory if it exists and is empty
            try:
                if os.path.exists(temp_chunk_dir) and not os.listdir(temp_chunk_dir):
                    os.rmdir(temp_chunk_dir)
                elif os.path.exists(temp_chunk_dir):
                     logging.warning(f"Temporary chunk directory {temp_chunk_dir} is not empty after processing.")
            except OSError as e:
                logging.error(f"Error removing temp chunk directory {temp_chunk_dir}: {e}")



# --- Gemini Function (MODIFIED with Fallback Logic) ---
def generate_flashcards_from_transcript(transcript_text, title):
    """
    Generates Anki flashcards using Gemini API with fallback model logic.
    Tries PRIMARY_GEMINI_MODEL first, falls back to FALLBACK_GEMINI_MODEL on error.
    Assumes Gemini returns JSON string with 'category' and 'flashcards'.
    Returns the parsed dictionary or None on error after fallback.
    """
    if not GEMINI_API_KEY:
        logging.error("GEMINI_API_KEY environment variable not set.")
        return None
    if not transcript_text or not transcript_text.strip():
        logging.warning("Transcript text is empty. Skipping flashcard generation.")
        return None

    logging.info("Initializing Gemini client...")
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logging.error(f"Failed to initialize Gemini client: {e}")
        return None

    # --- Prepare Content (same for both models) ---
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=f"""Video Title: {title}\n\nVideo Transcript: {transcript_text}"""),
            ],
        ),
    ]
    try:
        with open("system_prompt.txt", "r", encoding="utf-8") as file:
            system_instruction_text = file.read()
    except FileNotFoundError:
         logging.error("system_prompt.txt not found!")
         return None
    except Exception as e:
         logging.error(f"Error reading system_prompt.txt: {e}")
         return None

    generate_content_config = types.GenerateContentConfig(
        # Request JSON output if supported, otherwise parse text
        # response_mime_type="application/json",
        response_mime_type="text/plain",
        system_instruction=[
            types.Part.from_text(text=system_instruction_text),
        ],
    )

    # --- Attempt with Primary Model ---
    current_model_name = PRIMARY_GEMINI_MODEL
    response_stream = None
    generated_text = ""

    logging.info(f"Attempting generation with primary model: {current_model_name}")
    try:
        response_stream = client.models.generate_content_stream(
            model=current_model_name,
            contents=contents,
            config=generate_content_config,
        )
        logging.info(f"Successfully initiated stream with {current_model_name}.")

        # Process the stream if initiated successfully
        logging.info(f"Receiving stream from {current_model_name}...")
        for chunk in response_stream:
            if chunk.text:
                 generated_text += chunk.text
        logging.info(f"Finished receiving stream from {current_model_name}.")

    except (google_api_exceptions.NotFound, # Model not found
            google_api_exceptions.PermissionDenied, # User doesn't have access
            google_api_exceptions.ResourceExhausted, # Quota issues
            google_api_exceptions.InternalServerError, # Server-side issues
            google_api_exceptions.ServiceUnavailable,
            types.StopCandidateException, # Safety stops etc.
            types.BrokenResponseError,
            Exception # Catch broader errors too
           ) as e:
        logging.warning(f"Primary model ({current_model_name}) failed: {type(e).__name__}: {e}. Attempting fallback.")
        response_stream = None # Ensure stream is invalidated
        generated_text = ""    # Reset generated text

    # --- Attempt with Fallback Model (if primary failed) ---
    if response_stream is None: # Check if primary attempt failed
        current_model_name = FALLBACK_GEMINI_MODEL
        logging.info(f"Attempting generation with fallback model: {current_model_name}")
        try:
            response_stream = client.models.generate_content_stream(
                model=current_model_name,
                contents=contents,
                config=generate_content_config,
            )
            logging.info(f"Successfully initiated stream with {current_model_name}.")

            # Process the stream if initiated successfully
            logging.info(f"Receiving stream from {current_model_name}...")
            for chunk in response_stream:
                if chunk.text:
                     generated_text += chunk.text
            logging.info(f"Finished receiving stream from {current_model_name}.")

        except (google_api_exceptions.NotFound,
                google_api_exceptions.PermissionDenied,
                google_api_exceptions.ResourceExhausted,
                google_api_exceptions.InternalServerError,
                google_api_exceptions.ServiceUnavailable,
                types.StopCandidateException,
                types.BrokenResponseError,
                Exception
               ) as e:
            logging.error(f"Fallback model ({current_model_name}) also failed: {type(e).__name__}: {e}")
            response_stream = None # Indicate failure
            generated_text = ""    # Reset generated text

    # --- Process the final result (if any attempt succeeded) ---
    if not generated_text.strip() and response_stream is not None:
         # Handle case where stream finished but produced empty text
         logging.warning(f"Gemini model ({current_model_name}) finished but generated empty text content.")
         return None
    elif not generated_text.strip() and response_stream is None:
         # Handle case where both models failed to even start the stream or errored out
         logging.error(f"Both primary and fallback models failed to generate content.")
         return None

    # --- Parse the generated text as JSON (from whichever model succeeded) ---
    try:
        clean_text = generated_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[len("```json"):].strip()
        elif clean_text.startswith("```"):
            clean_text = clean_text[len("```"):].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-len("```")].strip()

        if not clean_text:
            logging.warning(f"Gemini generated empty text after removing markdown fences (Model used: {current_model_name}).")
            return None

        parsed_data = json.loads(clean_text)

        # Validate structure
        if not isinstance(parsed_data, dict) or \
           'category' not in parsed_data or not isinstance(parsed_data['category'], str) or \
           'flashcards' not in parsed_data or not isinstance(parsed_data['flashcards'], list):
             logging.error(f"Invalid JSON structure received from {current_model_name}: {parsed_data}")
             return None

        # Validate flashcards
        valid_cards = [card for card in parsed_data['flashcards']
                       if isinstance(card, dict) and 'front' in card and 'back' in card]
        if len(valid_cards) < len(parsed_data['flashcards']):
             logging.warning(f"Removed {len(parsed_data['flashcards']) - len(valid_cards)} invalid flashcard structures.")
        parsed_data['flashcards'] = valid_cards

        if not parsed_data['flashcards']:
             logging.warning(f"No valid flashcards found in the parsed JSON from {current_model_name}.")
             return None # Or return {'category': parsed_data['category'], 'flashcards': []} ?

        logging.info(f"Successfully parsed JSON from model '{current_model_name}' with category '{parsed_data['category']}' and {len(parsed_data['flashcards'])} flashcards.")
        return parsed_data

    except json.JSONDecodeError as e:
        logging.error(f"JSON parsing error from {current_model_name}: {e}. Text received:\n{generated_text}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error parsing JSON response from {current_model_name}: {e}. Text received:\n{generated_text}")
        return None


# --- JSON Card Data Functions (MODIFIED for Category) ---
def load_json_cards(filepath):
    """Loads card data (list of flashcards) from a specific category JSON file."""
    if not os.path.exists(filepath):
        logging.info(f"Card data file {filepath} not found. Starting with empty list.")
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Expecting the file to contain *only* the list of cards
            if isinstance(data, list):
                logging.info(f"Loaded {len(data)} cards from {filepath}")
                return data
            else:
                logging.warning(f"Data in {filepath} is not a list. Ignoring previous content.")
                return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {filepath}. Starting with empty list.")
        return []
    except Exception as e:
        logging.error(f"Error loading card data from {filepath}: {e}. Starting with empty list.")
        return []

def save_json_cards(filepath, cards_list):
    """Saves a list of card data to a specific category JSON file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            # Save *only* the list of cards
            json.dump(cards_list, f, indent=2, ensure_ascii=False)
        logging.info(f"Successfully saved {len(cards_list)} cards to {filepath}")
        return True
    except Exception as e:
        logging.error(f"Error saving card data to {filepath}: {e}")
        return False

def _invoke_ankiconnect(action, **params):
    """Helper function to make requests to AnkiConnect."""
    payload = {'action': action, 'version': 6, 'params': params}
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(ANKI_CONNECT_URL, json=payload, headers=headers, timeout=10) # Added timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        response_json = response.json()
        if response_json.get('error'):
            logging.error(f"AnkiConnect Error ({action}): {response_json['error']}")
            return None
        return response_json.get('result')
    except requests.exceptions.RequestException as e:
        logging.error(f"AnkiConnect Connection Error ({action}): {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"AnkiConnect JSON Decode Error ({action}): {e} - Response: {response.text[:200]}") # Log part of response
        return None
    except Exception as e: # Catch any other unexpected errors
         logging.error(f"AnkiConnect Unexpected Error ({action}): {e}")
         return None


def check_ankiconnect_connection():
    """Checks if AnkiConnect is reachable."""
    logging.info(f"Checking AnkiConnect connection at {ANKI_CONNECT_URL}...")
    result = _invoke_ankiconnect('version')
    if result is not None:
        logging.info(f"AnkiConnect connection successful (Version: {result}).")
        return True
    else:
        logging.error("AnkiConnect connection failed. Ensure Anki is running with AnkiConnect enabled.")
        return False

def create_anki_deck(deck_name):
    """Creates an Anki deck if it doesn't exist."""
    logging.info(f"Ensuring Anki deck exists: '{deck_name}'")
    result = _invoke_ankiconnect('createDeck', deck=deck_name)
    if result is None:
         # Error logged in _invoke_ankiconnect
         return False
    # createDeck returns null both on success and if the deck already exists
    # We consider both cases a success for our purpose here.
    logging.info(f"Deck '{deck_name}' ready.")
    return True


def add_cards_to_anki(flashcards, deck_name, source_title, raw_category_for_tagging):
    """Adds a list of flashcard dictionaries to the specified Anki deck."""
    if not flashcards:
        logging.info("No flashcards provided to add to Anki.")
        return 0, 0, 0 # Added, Duplicates, Failed

    if not deck_name:
        logging.warning("No deck name specified, using default.")
        deck_name = ANKI_DEFAULT_DECK_NAME

    # --- Ensure Deck Exists ---
    if not create_anki_deck(deck_name):
        logging.error(f"Cannot add cards because deck '{deck_name}' could not be created or verified.")
        return 0, 0, len(flashcards) # All failed

    # --- Verify Note Type Exists ---
    logging.debug(f"Verifying Anki Note Type '{ANKI_NOTE_TYPE}' exists...")
    model_names = _invoke_ankiconnect('modelNames')
    if model_names is None:
        logging.error("Failed to get model names from Anki. Cannot verify Note Type.")
        return 0, 0, len(flashcards) # All failed
    if ANKI_NOTE_TYPE not in model_names:
        logging.error(f"Anki Note Type '{ANKI_NOTE_TYPE}' not found in Anki. Please ensure it exists.")
        logging.error(f"Required fields: '{ANKI_FIELD_FRONT}', '{ANKI_FIELD_BACK}'" + (f", '{ANKI_FIELD_SOURCE}'" if ANKI_FIELD_SOURCE else ""))
        return 0, 0, len(flashcards) # All failed
    logging.debug(f"Note Type '{ANKI_NOTE_TYPE}' confirmed.")

    # --- Prepare and Add Notes ---
    added_count, duplicate_count, failed_count = 0, 0, 0
    notes_to_add = []

    logging.info(f"Preparing {len(flashcards)} notes for Anki deck '{deck_name}'...")

    # Prepare tags based on category (if enabled)
    anki_tags = []
    if ANKI_TAGS_FROM_CATEGORY and raw_category_for_tagging:
        # Sanitize the raw category name for use as a tag
        # Replace deck separators '::' with '_' for tags if desired
        tag_base = raw_category_for_tagging.replace("::", "_")
        sanitized_tag = sanitize_filename(tag_base)
        # Avoid adding generic default tags unless specifically desired
        if sanitized_tag and sanitized_tag.lower() != "default_category":
            anki_tags.append(sanitized_tag)
            logging.info(f"Using tag '{sanitized_tag}' based on category '{raw_category_for_tagging}'.")
        else:
            logging.info("Not adding tag from category (Category was default or sanitized to empty).")


    for index, card in enumerate(flashcards):
        if not isinstance(card, dict) or not card.get('front') or not card.get('back'):
            logging.warning(f"Skipping invalid card data structure at index {index}: {str(card)[:100]}")
            failed_count += 1
            continue

        # --- Build Note Fields ---
        fields = {
            ANKI_FIELD_FRONT: card['front'].strip(),
            ANKI_FIELD_BACK: card['back'].strip()
        }
        # Add source field if configured and provided
        if ANKI_FIELD_SOURCE:
            source_text = f"Source: {source_title}" if source_title else "Source: Unknown"
            fields[ANKI_FIELD_SOURCE] = source_text

        # --- Build Note Payload ---
        note = {
            'deckName': deck_name,
            'modelName': ANKI_NOTE_TYPE,
            'fields': fields,
            'options': {
                'allowDuplicate': False, # Set to false to prevent duplicates based on first field
                'duplicateScope': 'deck', # Check for duplicates only within this deck
                'duplicateScopeOptions': {'deckName': deck_name}
            },
            'tags': anki_tags # Add tags prepared earlier
        }
        notes_to_add.append(note)

    # --- Use addNotes for potentially better performance ---
    if notes_to_add:
        logging.info(f"Attempting to add {len(notes_to_add)} notes to Anki deck '{deck_name}' using addNotes...")
        results = _invoke_ankiconnect('addNotes', notes=notes_to_add)

        if results is None:
             # Error logged in _invoke_ankiconnect
             logging.error("Failed to add batch of notes to Anki.")
             failed_count = len(notes_to_add) # Assume all failed if the batch call failed
        elif isinstance(results, list):
            # Check results for each note: null means error/duplicate, note_id means success
            if len(results) != len(notes_to_add):
                 logging.warning(f"AnkiConnect 'addNotes' returned {len(results)} results, but {len(notes_to_add)} notes were sent. Counts may be inaccurate.")
                 # Fallback to assuming failure for discrepancy, though this is unlikely
                 failed_count = len(notes_to_add)

            else:
                for i, result in enumerate(results):
                    if result is None:
                        # Could be duplicate or other error. We can't easily distinguish with addNotes result.
                        # Let's try canAddNotes to check for duplicates specifically for the 'None' results.
                        # This adds overhead but gives better counts.
                        can_add_check = _invoke_ankiconnect('canAddNotes', notes=[notes_to_add[i]])
                        if can_add_check is not None and isinstance(can_add_check, list) and not can_add_check[0]:
                            # If canAddNotes returns [False], likely a duplicate
                             duplicate_count += 1
                             # logging.debug(f"Note {i+1} likely duplicate (addNotes returned null, canAddNotes returned false).")
                        else:
                             # If canAddNotes check failed or returned True (unexpected), count as failed add.
                             failed_count += 1
                             logging.warning(f"Note {i+1} failed to add (addNotes returned null, canAddNotes check inconclusive or indicated failure).")
                    elif isinstance(result, (int, float)):
                        # Success, result is the note ID
                        added_count += 1
                    else:
                        # Unexpected result format
                        logging.warning(f"Unexpected result for note {i+1} from addNotes: {result}. Counting as failed.")
                        failed_count += 1
        else:
             logging.error(f"Unexpected response type from AnkiConnect 'addNotes': {type(results)}. Assuming all failed.")
             failed_count = len(notes_to_add)

    # --- Final Summary Log for Anki Addition ---
    log_level = logging.INFO if added_count > 0 else logging.WARNING
    logging.log(log_level, f"Anki Add Complete for Deck '{deck_name}': Added={added_count}, Duplicates Found={duplicate_count}, Failed={failed_count}")
    return added_count, duplicate_count, failed_count


# --- Main Execution ---
# Make sure these imports are at the top of your file
import requests
import re # Should already be there
# ... other imports ...

# --- Main Execution ---
# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Starting YouTube Playlist Check...")
    script_start_time = time.time()

    # ... (initial checks remain the same) ...

    # --- NEW: Check AnkiConnect Connection Early ---
    anki_available = check_ankiconnect_connection()
    if not anki_available:
        logging.warning("AnkiConnect not available. Flashcards will be saved to JSON but not added to Anki.")
    # --------------------------------------------

    youtube = get_youtube_service()
    if not youtube: logging.error("Exiting: Could not initialize YouTube service."); sys.exit(1)

    temp_audio_dir = os.path.join(tempfile.gettempdir(), "ytaudio_flashcards")
    # ... (temp dir creation remains the same) ...

    # Load seen videos - This set will be updated ONLY with successfully processed videos
    seen_video_ids = load_seen_videos(STATE_FILE)
    logging.info(f"Loaded {len(seen_video_ids)} previously seen video IDs from {STATE_FILE}.")

    current_videos_dict = fetch_playlist_videos(youtube, PLAYLIST_ID)
    current_video_ids_from_playlist = set(current_videos_dict.keys()) # Rename for clarity

    if not current_videos_dict and not seen_video_ids:
         logging.warning("Could not fetch current videos and no previous state exists. Exiting run.")
         sys.exit(0)

    # Calculate videos to process: those in playlist but not in our *successfully processed* list
    new_video_ids_to_process = current_video_ids_from_playlist - seen_video_ids

    if new_video_ids_to_process: # Use the new variable name
        logging.info(f"Found {len(new_video_ids_to_process)} video(s) to process!")
        processed_in_this_run_count = 0 # Renamed for clarity
        cards_generated_in_run = 0
        cards_added_to_anki_in_run = 0
        cards_marked_duplicate_in_run = 0 # Added counter
        cards_failed_to_add_anki_in_run = 0 # Added counter
        updated_categories = set()
        successfully_processed_ids_this_run = set() # Track IDs completed in *this* run

        # Loop through the videos needing processing
        for video_id in new_video_ids_to_process:
            title = current_videos_dict.get(video_id, "Unknown Title")
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            logging.info(f"--- Processing video: '{title}' ({video_url}) ---")
            processed_successfully = False # Flag for this video

            # Skip age restricted check (moved inside try block maybe?)
            # if is_age_restricted(youtube, video_id):
            #     logging.warning(f"Skipping potentially age-restricted video: '{title}' (Will re-check during download if needed)")
            #     # Don't add to seen_video_ids here, let download handle it
            #     continue

            audio_file_path = None
            transcript_content = None
            try:
                # --- Age Restricted Check (moved here as download handles it better) ---
                # Optional: You can still pre-check, but cookies might bypass it anyway.
                # The download function will log if it fails due to restriction.

                # --- Audio Download ---
                audio_file_path = download_audio(video_url, temp_audio_dir)
                if not audio_file_path:
                    logging.warning(f"Audio download failed for '{title}'. Skipping further processing for this video. It will NOT be marked as seen.")
                    continue # Skip to next video

                # --- Transcription ---
                transcript_content = get_transcript_replicate(audio_file_path)
                if not transcript_content:
                    logging.warning(f"Could not get transcript for '{title}'. Skipping flashcard generation. It will NOT be marked as seen.")
                    continue # Skip to next video

                # --- Flashcard Generation (Gemini) ---
                logging.info(f"Attempting to generate flashcards for '{title}'...")
                generation_result = generate_flashcards_from_transcript(transcript_content, title)

                if generation_result and isinstance(generation_result.get('flashcards'), list) and generation_result['flashcards']:
                    # --- Determine Anki Deck Name (NEW LOGIC for Subdecks) ---
                    raw_category = generation_result.get('category', 'Default Category') # Use getter with default
                    new_cards = generation_result['flashcards']
                    sanitized_category = sanitize_filename(raw_category)

                    # Default to the full configured default deck name initially
                    anki_deck_name = ANKI_DEFAULT_DECK_NAME

                    # Check if the category is valid and not a generic placeholder
                    # Add any other generic/undesired category names Gemini might return here
                    undesired_categories = ["default_category", "unknown", "general", "misc"]
                    if sanitized_category and sanitized_category.lower() not in undesired_categories:
                        try:
                            # Extract the top-level deck name from the default setting (e.g., "Generated")
                            parent_deck_name = ANKI_DEFAULT_DECK_NAME.split('::', 1)[0]
                            # Construct the specific sub-deck name (e.g., "Generated::Specific_Category")
                            anki_deck_name = f"{parent_deck_name}::{sanitized_category}"
                        except IndexError:
                            # Fallback if ANKI_DEFAULT_DECK_NAME doesn't contain '::'
                            logging.warning(f"ANKI_DEFAULT_DECK_NAME ('{ANKI_DEFAULT_DECK_NAME}') does not follow 'Parent::Child' format. Using sanitized category as top-level deck: '{sanitized_category}'")
                            anki_deck_name = sanitized_category # Fallback to using category name directly

                    # If category was default/empty/invalid, anki_deck_name remains ANKI_DEFAULT_DECK_NAME

                    logging.info(f"Generated {len(new_cards)} cards for category '{raw_category}' (Sanitized: '{sanitized_category}', Target Anki Deck: '{anki_deck_name}').")

                    # --- 1. Save to JSON ---
                    # The JSON filename should still just use the sanitized category directly
                    json_card_file = os.path.join(DATA_DIR, f"{JSON_FILENAME_PREFIX}{sanitized_category}.json")
                    existing_cards = load_json_cards(json_card_file)
                    initial_card_count_category = len(existing_cards)
                    existing_cards.extend(new_cards)

                    if save_json_cards(json_card_file, existing_cards):
                        cards_added_this_video_json = len(existing_cards) - initial_card_count_category
                        cards_generated_in_run += cards_added_this_video_json
                        updated_categories.add(sanitized_category)
                        logging.info(f"Successfully saved {len(existing_cards)} total cards to {json_card_file} ({cards_added_this_video_json} new).")
                    else:
                         logging.error(f"Failed to save updated cards to {json_card_file} for video '{title}'.")
                         # Continue processing, but maybe don't mark as success? Your choice.
                         # For now, we'll still proceed to Anki and mark success later.

                    # --- 2. Add to Anki (If available) ---
                    if anki_available:
                        # Use the anki_deck_name determined above (which might be a subdeck)
                        logging.info(f"Attempting to add {len(new_cards)} cards to Anki deck '{anki_deck_name}'...")
                        # Pass the determined deck name and raw category for potential tagging
                        added, duplicates, failed = add_cards_to_anki(new_cards, anki_deck_name, title, raw_category)
                        cards_added_to_anki_in_run += added
                        cards_marked_duplicate_in_run += duplicates # Accumulate counts
                        cards_failed_to_add_anki_in_run += failed   # Accumulate counts
                        # Logging is handled within add_cards_to_anki
                    else:
                        logging.info(f"Skipping Anki addition for '{title}' as AnkiConnect is not available.")

                    # **** Mark as processed successfully ONLY if we got this far ****
                    processed_successfully = True


                elif generation_result: # Gemini ran but produced no cards
                     category = generation_result.get('category', 'unknown')
                     logging.warning(f"Gemini returned category '{category}' but no valid flashcards were generated/parsed for '{title}'.")
                     # Decide: Should this count as success? If Gemini succeeded but content wasn't useful,
                     # maybe we *do* want to mark it as seen so we don't retry Gemini? Let's say yes for now.
                     processed_successfully = True
                else: # generation_result is None (Gemini error)
                    logging.error(f"Flashcard generation failed for '{title}'. It will NOT be marked as seen.")
                    # Do NOT set processed_successfully = True


            except Exception as e:
                # Catch any unexpected error during the processing of a single video
                logging.error(f"Unexpected error processing video '{title}' ({video_id}): {e}", exc_info=True)
                # Ensure it's not marked as processed
                processed_successfully = False

            finally:
                # --- Cleanup Temp Audio ---
                if audio_file_path and os.path.exists(audio_file_path):
                    try:
                        os.remove(audio_file_path)
                        logging.info(f"Cleaned up temp audio: {audio_file_path}")
                    except OSError as e:
                        logging.error(f"Error removing temp audio {audio_file_path}: {e}")

                # --- Add to seen set ONLY if successful ---
                if processed_successfully:
                    logging.info(f"Successfully processed '{title}'. Marking as seen.")
                    seen_video_ids.add(video_id) # Add the ID to the master set
                    successfully_processed_ids_this_run.add(video_id) # Add to the set for this run's summary
                    processed_in_this_run_count += 1 # Increment counter for summary
                else:
                    logging.warning(f"Processing failed or was incomplete for '{title}'. It will NOT be marked as seen and may be retried next run.")

            # Optional: time.sleep(1)

        # --- Summary Logging (Improved) ---
        total_attempted = len(new_video_ids_to_process)
        log_summary = (f"Finished processing loop. Attempted={total_attempted}, "
                       f"Successfully Processed (marked as seen)={processed_in_this_run_count}.")

        if cards_generated_in_run > 0:
            log_summary += f" Generated/Saved {cards_generated_in_run} cards to JSON across {len(updated_categories)} categories."
        elif processed_in_this_run_count > 0: # Processed some but generated 0 cards
             log_summary += f" No new flashcards were generated or saved to JSON."

        if anki_available:
            log_summary += (f" Anki: Added={cards_added_to_anki_in_run}, "
                            f"Duplicates={cards_marked_duplicate_in_run}, "
                            f"Failed={cards_failed_to_add_anki_in_run}.")
        else:
             if cards_generated_in_run > 0 : # Only mention skipping if cards were generated
                  log_summary += f" Anki addition skipped (AnkiConnect unavailable)."
        logging.info(log_summary)

        # --- Update State File ---
        # Save the updated set of seen video IDs (includes old ones + newly successful ones)
        # Only save if there were attempts, even if none succeeded this run, to capture potential removals if playlist changed.
        # However, the most robust is to save *only* if successful additions happened OR if videos were removed from playlist.
        # Let's save if any were successfully processed in this run.
        if successfully_processed_ids_this_run:
             save_seen_videos(STATE_FILE, seen_video_ids)
        else:
             logging.info("No videos were successfully processed in this run. State file not updated.")


    else: # No new_video_ids_to_process
        logging.info("No new videos found in the playlist requiring processing.")
        # Optional: You might still want to save the state if videos could have been *removed*
        # from the playlist compared to the last run, but `seen_video_ids` wouldn't reflect that.
        # A more complex diff would be needed. For now, only saving on success is safer.
        # save_seen_videos(STATE_FILE, seen_video_ids) # Uncomment if you want to save even if no new videos processed

    logging.info(f"Playlist check finished in {time.time() - script_start_time:.2f} seconds.")