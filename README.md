# BusPCRT

`BusPCRT` is the onboard project for passenger-flow counting, service monitoring, camera recording, and maintenance tooling on the bus PC.

## `pcrt` CLI

`pcrt` is the main service command for working with the onboard system from the terminal.

It can:

- show the current board summary
- show service status
- stream logs
- start, stop, and restart services
- launch the interactive door simulator
- manually record video from a selected camera

### Install `pcrt` Into PATH

If the project is installed on the bus in `/opt/BusPCRT`, run:

```bash
sudo /opt/BusPCRT/scripts/services/pcrt_cli.sh install \
  --project-root /opt/BusPCRT \
  --python /opt/BusPCRT/.venv/bin/python
```

After that:

```bash
which pcrt
pcrt help
```

If needed, remove it with:

```bash
sudo /opt/BusPCRT/scripts/services/pcrt_cli.sh uninstall
```

### Help

General help:

```bash
pcrt --help
pcrt help
```

Help for a specific command:

```bash
pcrt help summary
pcrt help status
pcrt help logs
pcrt help doors
pcrt help record
```

## Main Commands

### Summary

Show overall bus health, core services, monitor snapshot, connectivity, cameras, storage, and buffer state:

```bash
pcrt summary
```

JSON output:

```bash
pcrt summary --json
```

### List Targets

Show available aliases and units:

```bash
pcrt list
```

### Status

Show service status by alias or full unit name:

```bash
pcrt status processor
pcrt status monitor door
pcrt status cam1
pcrt status buspcrt-monitor.service
```

Group alias for all camera recorder services:

```bash
pcrt status cams
```

JSON output:

```bash
pcrt status cams --json
```

### Logs

Show last 100 log lines:

```bash
pcrt logs processor
pcrt logs monitor
pcrt logs cam1
```

Show logs from all three camera recorder services:

```bash
pcrt logs cams
```

Follow logs live:

```bash
pcrt logs processor -f
pcrt logs cams -f
```

Custom line count:

```bash
pcrt logs monitor -n 300
```

### Service Control

These commands require `root` or `sudo`.

```bash
sudo pcrt restart processor
sudo pcrt restart cam1
sudo pcrt stop monitor
sudo pcrt start monitor
```

`cams` is intentionally not allowed for mutating commands, so camera services must be managed explicitly one by one.

### Door Simulator

Launch the interactive live door simulator:

```bash
sudo pcrt doors live
```

This temporarily stops `buspcrt-door-gateway.service` if it is active, starts the simulator, and restores the real service when you exit.

The simulator uses the current `ZMQ_IPC_ENDPOINT` from `config.env` by default.

### Manual Camera Recording

Record from a specific camera:

```bash
sudo pcrt record cam1
```

With fixed duration:

```bash
sudo pcrt record cam2 --duration 15
```

With custom output directory:

```bash
sudo pcrt record cam3 --duration 20 --output-dir /tmp/pcrt-captures/cam3
```

Behavior:

- if the matching `buspcrt-recorder@camN.service` is active, `pcrt` temporarily stops it
- the recording runs until `Ctrl+C` or until `--duration` expires
- by default, files are saved to `/var/lib/pcrt/manual-captures/<cam>`
- output format is the project session format: `mkv + meta.json`

## Built-In Aliases

Service aliases:

- `processor`
- `monitor`
- `door`
- `cam1`
- `cam2`
- `cam3`
- `updater`
- `updater-timer`
- `cleanup`

Read-only group alias:

- `cams`

`cams` works in:

- `pcrt status cams`
- `pcrt logs cams`

## Config Sources

`pcrt` reads configuration from:

- `/etc/pcrt/device.env`
- `config.env`
- `monitor.env`
- local `monitor.sqlite`
- `recorder-cam.env`
- `recorder-cam2.env`
- `recorder-cam3.env`
