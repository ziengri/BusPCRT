# BusPCRT

`BusPCRT` is the onboard project for passenger-flow counting, service monitoring, camera recording, and maintenance tooling on the bus PC.

## `pcrt` CLI

`pcrt` is the main service command for working with the onboard system from the terminal.

Recorder cameras use shared fleet configs from `recorder-cam*.env`. The active camera set on each bus is selected by `/etc/pcrt/device.env::NUMBER_CAMS`.

It can:

- show the current board summary
- show service status
- stream logs
- start, stop, and restart services
- launch the interactive door simulator
- manually record video from a selected camera

### Install `pcrt` Into PATH

If the project is installed on the bus in `/opt/pcrt`, run:

```bash
sudo /opt/pcrt/scripts/services/pcrt_cli.sh install \
  --project-root /opt/pcrt \
  --python /opt/pcrt/.venv/bin/python
```

After that:

```bash
which pcrt
pcrt help
```

If needed, remove it with:

```bash
sudo /opt/pcrt/scripts/services/pcrt_cli.sh uninstall
```

### Install Or Reinstall Services

To reinstall all BusPCRT services consistently from the current `/etc/pcrt/device.env`:

```bash
sudo /opt/pcrt/scripts/services/install_services.sh
```

The script removes old systemd units first, then installs fixed services and only active recorder services. For example, with `NUMBER_CAMS=3`, an old `buspcrt-recorder@cam4.service` is removed and not re-enabled.

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
pcrt status cam4
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

Show logs from all discovered camera recorder services:

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
sudo pcrt restart cam4
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
The door count comes from `/etc/pcrt/device.env::NUMBER_CAMS`. `door_gateway.env::DOOR_COUNT` is only an optional manual override for debugging.

Door packets now use mixed binary/ASCII RS-232 payloads:

```text
!DOORS:1=\x00,0.0;2=\x01,12.4;3=\x00,0.1;
```

Where each door entry is `<door_id>=<state_byte>,<voltage>;`.
`state_byte` remains binary `\x00` or `\x01`, and `voltage` is sent as ASCII decimal volts.
`door_gateway` publishes this data to `doors.state` and `door.N.state`; recorder and processor still use only the door state, while voltage is available for local diagnostics and remote troubleshooting.

### Direct RS-232 Door Reader

Read what comes from `Signal` directly over RS-232:

```bash
sudo pcrt doors direct
```

Optional fixed serial port override:

```bash
sudo pcrt doors direct --serial-port /dev/ttyS1
```

This temporarily stops `buspcrt-door-gateway.service` if it is active, runs `scripts/test_rs232_direct.py`, and restores the real service when you exit.

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
sudo pcrt record cam4 --duration 20 --output-dir /tmp/pcrt-captures/cam4
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
- `updater`
- `updater-timer`
- `cleanup`

Camera aliases are generated dynamically from `CAMERA_ID` values in `recorder-cam*.env`, filtered by `/etc/pcrt/device.env::NUMBER_CAMS`, for example:

- `cam1`
- `cam2`
- `cam3`
- `cam4`

Read-only group alias:

- `cams`

`cams` works in:

- `pcrt status cams`
- `pcrt logs cams`

## Config Sources

`pcrt` reads configuration from:

- `/etc/pcrt/device.env` (`BUS_ID`, `NUMBER_CAMS=3|4`)
- `config.env`
- `monitor.env`
- `door_gateway.env`
- local `monitor.sqlite`
- fleet `recorder-cam*.env`

## Camera And Door Expansion

`recorder-cam*.env` files are fleet configs and may be filled identically on every onboard PC. The per-bus switch is `NUMBER_CAMS` in `/etc/pcrt/device.env`.

For a 3-camera / 3-door bus:

```dotenv
NUMBER_CAMS=3
```

For a 4-camera / 4-door bus:

```dotenv
NUMBER_CAMS=4
```

When `NUMBER_CAMS=3`, `recorder-cam4.env` is ignored even if it is filled. When `NUMBER_CAMS=4`, `cam4` becomes active for `pcrt`, monitoring, recorder service installation, and the door protocol publishes `door.4.state`.

During firstboot, `setup_firstboot.sh` writes `/etc/pcrt/device.env`, renders `/etc/pcrt/frpc.toml`, reinstalls `reverse-tunnel.service`, and then runs `/opt/pcrt/scripts/services/install_services.sh` so systemd matches the selected bus configuration.
