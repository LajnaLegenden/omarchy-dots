-- Extra autostart processes.
-- o.launch_on_start("my-service")

-- Night light. hyprsunset holds the colour temperature; the actual schedule and
-- the fading live in the omarchy-nightlight-schedule user timer.
o.launch_on_start("hyprsunset")
