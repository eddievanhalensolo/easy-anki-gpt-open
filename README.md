# Automated YouTube Playlist to Anki Flashcards (via AI) 🤖📚
_by Simon Herbst_

Do you love learning from YouTube videos but struggle to remember the key information afterward? Do you want to move beyond surface-level watching and truly **ingrain** the knowledge, but find the idea of manually creating flashcards for every video tedious? This project is the solution! Simply create a dedicated playlist on YouTube (e.g., "Flashcard Worthy") and add any video you want to learn deeply. This script will automatically detect new additions, download the audio, use AI to create relevant flashcards, and add them directly to your Anki collection. When combined with Anki's built-in sync (or add-ons like Anki Sync Media for older setups), your new flashcards appear seamlessly on your Anki mobile app, ready for review!

This script automates the process of creating Anki flashcards from new videos added to a specified YouTube playlist. It downloads the audio, transcribes it using AI (Whisper), generates categorized Q&A flashcards using another AI (Google Gemini), saves the flashcards locally in JSON format, and adds them directly to your Anki collection via AnkiConnect.

## Features ✨

*   **Playlist Monitoring:** Checks a YouTube playlist for new videos since the last run.
*   **Audio Extraction:** Downloads audio from YouTube videos using `yt-dlp` (supports cookies for age-restricted/member content).
*   **AI Transcription:** Transcribes audio using Replicate's high-speed Whisper models (with fallback).
*   **AI Flashcard Generation:** Uses Google's Gemini models (with fallback and configurable system prompt) to analyze the transcript and generate relevant, categorized flashcards (Q&A format).
*   **Anki Integration:**
    *   Connects to a running Anki instance via the AnkiConnect add-on.
    *   Creates Anki decks based on the AI-generated category (as sub-decks under a configured parent deck, e.g., `Generated::Physics`).
    *   Adds generated flashcards to the appropriate deck.
    *   Uses configurable Anki Note Types and Fields.
    *   Optionally adds the video title/URL to a specified source field.
    *   Optionally adds tags to cards based on the AI-generated category.
    *   Checks for and skips adding duplicate cards within the target deck.
*   **Local Data Storage:** Saves generated flashcards categorized into JSON files in a specified data directory.
*   **State Management:** Keeps track of processed videos in a state file (`playlist_state.json`) to avoid duplicates.
*   **Configuration:** Uses a `.env` file for easy management of API keys, playlist ID, Anki settings, etc.
*   **Robust Logging:** Logs detailed information about the process to both the console and a file (`youtube_flashcard_script.log`).
*   **Fallback Mechanisms:** Uses fallback models for both Whisper (via Replicate) and Gemini if primary models fail.

## Prerequisites 📋

Before you begin, ensure you have the following installed and set up:

1.  **Python:** Version 3.8 or higher recommended.
2.  **pip:** Python package installer (usually comes with Python).
3.  **Git:** For cloning the repository.
4.  **Anki:** The desktop application must be installed. ([Download Anki](https://apps.ankiweb.net/))
5.  **AnkiConnect Add-on:** Install this add-on within Anki.
    *   In Anki, go to `Tools` -> `Add-ons` -> `Get Add-ons...`
    *   Paste the code: `2055492159`
    *   Click `OK`, then restart Anki.
    *   Ensure Anki is **running** with your desired profile open when you run the script.
6.  **ffmpeg:** Required by `yt-dlp` for audio processing. Download it and ensure it's in your system's PATH.
    *   [ffmpeg Download](https://ffmpeg.org/download.html)
    *   Tutorials for adding to PATH: [Windows](https://www.wikihow.com/Install-FFmpeg-on-Windows), [macOS/Linux](https://opensource.com/article/17/6/ffmpeg-convert-media-file-formats) (often available via package managers like `brew` or `apt`).
7.  **API Keys & Accounts:**
    *   **Google Cloud API Key:** For the YouTube Data API v3.
        *   Go to the [Google Cloud Console](https://console.cloud.google.com/).
        *   Create a project (or use an existing one).
        *   Enable the "YouTube Data API v3".
        *   Create API credentials (API Key).
    *   **Google AI Studio API Key:** For the Gemini API.
        *   Go to [Google AI Studio](https://aistudio.google.com/).
        *   Click "Get API key".
    *   **Replicate API Token:** For the Whisper transcription models.
        *   Sign up or log in at [Replicate](https://replicate.com/).
        *   Go to your Account settings to find or create your API token.
8.  **(Optional but Recommended) Browser Cookies:** To download age-restricted or members-only videos, you'll need to export your YouTube cookies.
    *   Use a browser extension like "[Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid)" (Chrome) or "[cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)" (Firefox).
    *   Export the cookies specifically for `youtube.com` and save the file as `cookies.txt` in the *same directory as the script*.

## Installation & Setup ⚙️

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: If `requirements.txt` is missing, the developer should create it using `pip freeze > requirements.txt` before publishing.)*

4.  **Configure Environment Variables:**
    *   Create a file named `.env` in the project's root directory.
    *   Copy the contents of `.env.example` (if provided) or add the following variables, replacing the placeholder values with your actual credentials and settings:

    ```dotenv
    # --- YouTube API ---
    YOUTUBE_API_KEY=YOUR_GOOGLE_CLOUD_API_KEY_HERE
    YOUTUBE_PLAYLIST_ID=YOUR_YOUTUBE_PLAYLIST_ID_HERE

    # --- AI APIs ---
    GEMINI_API_KEY=YOUR_GOOGLE_AI_STUDIO_API_KEY_HERE
    REPLICATE_API_TOKEN=YOUR_REPLICATE_API_TOKEN_HERE

    # --- AnkiConnect ---
    # Default is usually fine if AnkiConnect is running locally
    ANKI_CONNECT_URL=http://127.0.0.1:8765

    # --- Anki Configuration (MUST MATCH YOUR ANKI SETUP) ---
    # The top-level deck. Sub-decks will be created under this based on category.
    # Example: "Generated::YouTube"
    ANKI_DEFAULT_DECK_NAME=Generated::YouTube Flashcards

    # The exact name of the Anki Note Type you want to use
    ANKI_NOTE_TYPE=Basic

    # The exact name of the field for the question/front of the card
    ANKI_FIELD_FRONT=Front

    # The exact name of the field for the answer/back of the card
    ANKI_FIELD_BACK=Back

    # Optional: The exact name of the field to store source info (video title)
    # Leave blank or comment out if you don't want to store the source.
    ANKI_FIELD_SOURCE=Source

    # Optional: Use the AI-generated category as an Anki tag? (true/false)
    ANKI_TAGS_FROM_CATEGORY=true

    # --- Data Storage ---
    # Directory to store state file, log file, and generated JSON card files.
    # '.' means the current directory where the script is run.
    # Use an absolute path for more robustness if running via cron etc.
    DATA_DIR=C:\path\to\your\preferred\data\folder # Example for Windows automation
    ```
    ***Important for Automation:** When using Task Scheduler, using relative paths like `.` for `DATA_DIR` can be unreliable as the "current directory" might not be what you expect. It's **highly recommended** to use an absolute path (e.g., `C:\Users\YourUser\Documents\YouTubeAnkiData`) for `DATA_DIR` if you plan to automate the script.*

5.  **Verify Anki Note Type and Fields:**
    *   Open Anki.
    *   Go to `Tools` -> `Manage Note Types`.
    *   Select the Note Type you specified in `ANKI_NOTE_TYPE`.
    *   Click `Fields...`.
    *   Ensure the field names **exactly** match what you put in `ANKI_FIELD_FRONT`, `ANKI_FIELD_BACK`, and `ANKI_FIELD_SOURCE` (if used) in your `.env` file. Case sensitivity matters!

6.  **Place `cookies.txt` (Optional):**
    *   If you exported your YouTube cookies, save the file as `cookies.txt` in the same directory as the main Python script (e.g., `process_playlist.py`).

7.  **Customize `system_prompt.txt`:**
    *   Review the `system_prompt.txt` file. This file contains the instructions given to the Gemini AI model for generating flashcards.
    *   Modify it to change the style, format, or focus of the generated flashcards if desired. Ensure it still asks for the required JSON output structure (`{"category": "...", "flashcards": [{"front": "...", "back": "..."}, ...]}`).

## Usage ▶️

1.  **Start Anki:** Make sure the Anki application is running and the correct profile is open. *The script needs Anki open to use AnkiConnect.*
2.  **Activate Virtual Environment:** If you created one, activate it (`source venv/bin/activate` or `.\venv\Scripts\activate`).
3.  **Run the Script Manually:** Execute the main Python script from your terminal:
    ```bash
    python process_playlist.py # Or whatever you named the main script file
    ```
4.  **Observe:** The script will:
    *   Log its progress to the console and the log file (`youtube_flashcard_script.log` in your `DATA_DIR`).
    *   Fetch the playlist details.
    *   Identify new videos.
    *   For each new video:
        *   Download audio.
        *   Transcribe audio (this can take time depending on video length and Replicate's queue).
        *   Generate flashcards using Gemini (can also take some time).
        *   Save cards to a category-specific JSON file in `DATA_DIR`.
        *   Add cards to the appropriate Anki sub-deck.
    *   Update the `playlist_state.json` file.

### Automation (Optional) ⚙️➡️⏱️

Instead of running the script manually, you can automate it.

**On Windows (Using Task Scheduler):**

This example sets up the script to run automatically every time you unlock your computer (assuming Anki is usually running then).

1.  **Open Task Scheduler:** Press `Win + R`, type `taskschd.msc`, and press Enter.
2.  **Create Basic Task:** In the right-hand Actions pane, click "Create Basic Task...".
3.  **Name and Description:** Give it a name (e.g., "YouTube Anki Flashcard Sync") and an optional description. Click Next.
4.  **Trigger:** Select "When a specific event is logged". Click Next.
    *   **Log:** Select `Microsoft-Windows-TerminalServices-LocalSessionManager/Operational`
    *   **Source:** Select `TerminalServices-LocalSessionManager`
    *   **Event ID:** Enter `25` (This corresponds to "Session unlock").
    *   Click Next.
    *   *(Alternatively, you could choose "Daily" or other triggers based on your preference.)*
5.  **Action:** Select "Start a program". Click Next.
6.  **Program/script:**
    *   You need to run the python executable *from your virtual environment*. Find the full path to `python.exe` inside your `venv\Scripts` folder.
    *   Example: `C:\path\to\your\project\venv\Scripts\python.exe`
7.  **Add arguments (optional):**
    *   Enter the full path to your main Python script file.
    *   Example: `C:\path\to\your\project\process_playlist.py`
8.  **Start in (optional):**
    *   **Crucially**, set this to the directory where your script, `.env` file, and `cookies.txt` are located. This ensures the script can find these files.
    *   Example: `C:\path\to\your\project\`
9.  **Finish:** Review the summary and click Finish.
10. **Refine Settings (Important):**
    *   Find your newly created task in the Task Scheduler Library.
    *   Right-click it and select "Properties".
    *   **General Tab:** Consider checking "Run with highest privileges" if you encounter permission issues, though usually not necessary. Ensure the user account is correct.
    *   **Conditions Tab:** Under the "Power" section, you might want to *uncheck* "Start the task only if the computer is on AC power" if you use a laptop on battery.
    *   **Settings Tab:**
        *   Consider checking "Run task as soon as possible after a scheduled start is missed".
        *   Adjust "If the task fails, restart every:" if desired (e.g., restart after 5 minutes, attempt 3 times).
        *   Set "If the task is already running, then the following rule applies:" to "Do not start a new instance" or "Queue a new instance". "Do not start" is usually safer to prevent multiple overlapping runs.
    *   Click OK.

**On macOS/Linux (Using `cron`):**

*   Open your terminal.
*   Type `crontab -e` to edit your cron jobs.
*   Add a line similar to this (adjust paths and schedule):
    ```cron
    # Run YouTube Anki sync daily at 8:00 AM
    0 8 * * * /path/to/your/project/venv/bin/python /path/to/your/project/process_playlist.py >> /path/to/your/project/data/cron.log 2>&1
    ```
*   **Explanation:**
    *   `0 8 * * *`: Run daily at 8:00 AM (Minute Hour Day Month DayOfWeek). Use [crontab.guru](https://crontab.guru/) to build your schedule.
    *   `/path/to/your/project/venv/bin/python`: Full path to Python in your virtual environment.
    *   `/path/to/your/project/process_playlist.py`: Full path to your script.
    *   `>> /path/to/your/project/data/cron.log 2>&1`: Redirects standard output and standard error to a log file (optional but recommended for debugging cron jobs). Ensure the `data` directory exists or adjust the path.
*   Save and exit the editor.

**Important Note for Automation:** Ensure Anki is running when the scheduled task executes, otherwise, the script won't be able to connect via AnkiConnect. The "On workstation unlock" trigger on Windows is often effective because people typically have Anki running when actively using their computer.

## Output 📄

The script produces the following:

*   **Anki Cards:** New flashcards added to your Anki collection, organized into sub-decks under your `ANKI_DEFAULT_DECK_NAME` (e.g., `Generated::YouTube Flashcards::Specific Category Name`). Cards might also have tags and source information depending on your configuration.
*   **JSON Files:** Located in the `DATA_DIR`, named like `Category_Name.json`. Each file contains a list of flashcards (`{"front": "...", "back": "..."}`) generated for that category across all processed videos.
*   **Log File:** `youtube_flashcard_script.log` (or configured name) within `DATA_DIR`, containing detailed execution logs. Check this file first if you encounter issues.
*   **State File:** `playlist_state.json` within `DATA_DIR`, containing the IDs of YouTube videos that have been successfully processed.

## Troubleshooting 🛠️

*   **API Key Errors:**
    *   Double-check the keys in your `.env` file are correct and have no extra spaces.
    *   Ensure the YouTube Data API v3 is enabled in your Google Cloud project.
    *   Check your API quotas on Google Cloud, Google AI Studio, and Replicate.
*   **AnkiConnect Errors:**
    *   Is Anki running with the correct profile open?
    *   Is the AnkiConnect add-on installed and enabled?
    *   Is the `ANKI_CONNECT_URL` in `.env` correct (usually `http://127.0.0.1:8765`)?
    *   Check AnkiConnect's configuration in Anki (`Tools` -> `Add-ons` -> `AnkiConnect` -> `Config`) to ensure the webserver is enabled and the allowed origins (`webCorsOriginList`) include `http://127.0.0.1`.
*   **`yt-dlp` Download Errors:**
    *   "Video unavailable" or "Private video": The video might have been removed or made private.
    *   "Age restriction": Ensure `cookies.txt` is correctly exported, named, and placed in the script's directory. The cookies might have expired - try exporting them again.
    *   Network errors: Check your internet connection.
    *   `ffmpeg` errors: Ensure `ffmpeg` is installed correctly and accessible in your system's PATH.
*   **Transcription Errors (Replicate):**
    *   Check Replicate status page for outages.
    *   Check your Replicate account balance/quota.
    *   The audio might be silent or too noisy.
*   **Flashcard Generation Errors (Gemini):**
    *   Check your Google AI Studio API key and quotas.
    *   Review `system_prompt.txt` - it might be confusing the model.
    *   The transcript might be too short, noisy, or contain sensitive content triggering safety filters. Check the logs for specific Gemini errors.
*   **JSON Parsing Errors:**
    *   Gemini might have failed to produce valid JSON. Check the logs for the raw text received from Gemini. You might need to adjust `system_prompt.txt`.
*   **Anki Note Type / Field Errors:**
    *   "Note type not found" or "Field not found": The names in your `.env` (`ANKI_NOTE_TYPE`, `ANKI_FIELD_FRONT`, etc.) **must exactly match** the names in your Anki setup (case-sensitive). Verify them in Anki via `Tools` -> `Manage Note Types`.
*   **Task Scheduler / Cron Issues:**
    *   **Paths:** Ensure all paths (Python executable, script file, `Start in` directory / cron paths) are absolute and correct.
    *   **Permissions:** The user account running the task needs permission to read/write in the script directory and `DATA_DIR`.
    *   **Environment:** Scheduled tasks might not inherit the same environment variables as your interactive shell. Using absolute paths and ensuring `.env` is loaded correctly (which the script does via `load_dotenv()`) is crucial. Using an absolute path for `DATA_DIR` in `.env` is highly recommended.
    *   **Anki Not Running:** The script will fail if Anki isn't running when the task executes.
    *   **Logging:** Check the main script log (`youtube_flashcard_script.log`) and any cron-specific logs for errors.
*   **Dependency Issues:**
    *   Ensure you ran `pip install -r requirements.txt` within your activated virtual environment. If running via Task Scheduler/cron, ensure the correct Python executable *from the venv* is being used.
*   **General Issues:**
    *   **Check the log file!** (`youtube_flashcard_script.log` in `DATA_DIR`) It often contains detailed error messages.
    *   Ensure all files (`.env`, `cookies.txt`, `system_prompt.txt`, the script itself) are in the correct locations, especially relative to the `Start in` directory for Task Scheduler.

## Contributing 🤝

Contributions, issues, and feature requests are welcome! Please feel free to:

*   Report bugs or suggest features by opening an issue.
*   Submit pull requests with improvements.

## License ⚖️

This project is licensed under the [MIT License](LICENSE). *(You should create a file named `LICENSE` in your repository and paste the contents of the MIT license into it)*.
