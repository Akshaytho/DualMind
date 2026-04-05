# DualMind v2

Two Claude Code CLI instances debating and building through a shared repo. No GUI. Pure terminal.

## Setup (one time)
```bash
git clone https://github.com/Akshaytho/DualMind.git ~/DualMind
echo "YOUR_GITHUB_TOKEN" > ~/DualMind/bridge/.secrets
chmod +x ~/DualMind/bridge/watcher.sh
```

## Run
```bash
cd ~/DualMind && bash bridge/watcher.sh
```

## Stop
```bash
pkill -f watcher.sh
```
