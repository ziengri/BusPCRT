scripts/services/sessions_cleanup_service.sh install --project-root /opt/BusPCRT --env /opt/BusPCRT/config.env
scripts/services/pcrt_cli.sh install --project-root /opt/BusPCRT --python /opt/BusPCRT/.venv/bin/python
scripts/services/door_gateway_service.sh install --project-root /opt/BusPCRT --env /opt/BusPCRT/door_gateway.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/processor_service.sh install --project-root /opt/BusPCRT --env /opt/BusPCRT/processor.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/monitor_service.sh install --project-root /opt/BusPCRT --env /opt/BusPCRT/monitor.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/recorder_service.sh install --instance cam1 --project-root /opt/BusPCRT --env recorder-cam.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/recorder_service.sh install --instance cam2 --project-root /opt/BusPCRT --env recorder-cam2.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/recorder_service.sh install --instance cam3 --project-root /opt/BusPCRT --env recorder-cam3.env --python /opt/BusPCRT/.venv/bin/python
scripts/services/recorder_service.sh uninstall
