# FromSoftware Troubleshooter

Standalone diagnostic tool for FromSoftware PC games.

## Supported Games

- Elden Ring
- Elden Ring Nightreign
- Dark Souls Remastered
- Dark Souls II: Scholar of the First Sin
- Dark Souls III

## Checks

- Game installation & folder
- Game executable size (detects modified/pirated exes)
- steam_api64.dll integrity
- regulation.bin validity (where applicable)
- Piracy indicators (OnlineFix, steam_emu, etc.)
- Problematic running processes (Overwolf, RTSS, Process Lasso, etc.)
- VPN clients
- Steam running as administrator
- Save file permissions and size
- Disk space

File size ranges are fetched from GitHub and fall back to the bundled
`game_file_sizes.json` if offline.

## Usage

Download `FromSoftware Troubleshooter.exe` from Releases and run it.
Set your game folder and save file path via the buttons at the top,
then select the game from the dropdown.

## Building from Source

See [DEVELOPMENT.md](DEVELOPMENT.md).