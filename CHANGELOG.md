# FromSoftware Troubleshooter - Release History

## Release 1.9.0
**Released:** November 13, 2026

### New Features

- Dark Souls II gets the Seamless Co-op install and launcher admin checks
- Disk space check: free space on the drives holding the saves and the game, with a warning under 1 GB
- The save file check runs when a save is found
- The version shows in the window title, and the copied report includes the version, OS and game folder
- Releases are signed: the Windows exe with a code signing certificate, the Linux AppImage with GPG

### Bug Fixes

- A check that crashes shows as a warning card and the run finishes instead of hanging
- Switching game during a run no longer mixes the results of two games
- Scheduled task checks and the HidHide, Vanguard and RTCore64 service checks work on non-English Windows
- Permission fix commands target the game's own save folder instead of all of AppData, and leave out missing folders
- After a game update newer than the recorded file sizes, an unexpected exe or regulation.bin size shows as info instead of a warning
- The firewall rule check and the Steam admin check no longer time out
- Downloads verify certificates with the bundled certifi list
- The window icon loads in the built app
- Switching games no longer asks "Game Not Found" each time; the game folder line says it wasn't found automatically instead
- On Linux the Steam admin card is hidden
- Handle unavailable Steam drives during library scan ([62bb691](https://github.com/Hapfel1/fromsoftware-troubleshooter/commit/62bb691a9a5c17e6720c66e11b01389ae79f8de6))

### Performance

- Finding the game runs in the background, and the process list and Steam libraries are read once per run instead of once per check

### Game File Sizes

- Update elden_ring to build 25827938 ([a73dfb1](https://github.com/Hapfel1/fromsoftware-troubleshooter/commit/a73dfb1f3ecc153fba9626f5ab2240c9335323bf))

### Documentation

- Switch to the source-available license; earlier versions stay MIT (#8) ([833a6f9](https://github.com/Hapfel1/fromsoftware-troubleshooter/commit/833a6f9728d3859835b358f8715bb71832aa86ae))

