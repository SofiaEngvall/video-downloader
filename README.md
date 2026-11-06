#### Installation (Linux)

##### Download:
`git clone git@github.com:SofiaEngvall/video-downloader.git`<br>

##### Make the file executable
`cd video-downloader`<br>
`chmod +x dl.py`<br>

##### Create a virtual environment
`python3 -m venv .venv`<br>
`pip install yt_dlp`<br>

##### Start using the environment
`source .venv/bin/activate`<br>

##### Exit the virtual environment by running
`deactivate`

##### Add alias
`nano ~/.zshrc (or what shell you use)`<br>
append `alias dl="~/dl/dl.py"` to the end of the file<br>

### Running the program
`dl https://www.twitch.tv/videos/2920531262`


