# FromSoftware Troubleshooter

Standalone diagnostic tool for FromSoftware PC games.

## Supported Games

- Elden Ring
- Elden Ring Nightreign
- Dark Souls Remastered
- Dark Souls II: Scholar of the First Sin
- Dark Souls III
- Sekiro
- Armored Core 6

## Checks

- Game installation & folder
- Game executable size (detects modified/pirated exes)
- steam_api64.dll integrity
- regulation.bin validity (where applicable)
- Problematic running processes (Overwolf, RTSS, Process Lasso, etc.)
- VPN clients
- Steam running as administrator
- Disk space

File size ranges are fetched from GitHub and fall back to the bundled
`game_file_sizes.json` if offline.

## Usage

Download `FromSoftware Troubleshooter.exe` from Releases and run it.
Select the game you want to troubleshoot.

## Building from Source

See [DEVELOPMENT.md](DEVELOPMENT.md).