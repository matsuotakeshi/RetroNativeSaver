"""Unchanged timing calculations from v0.20.79 main, test only."""

def cycle_frame_timing(av_infos):
    fps_values = []
    for av in av_infos:
        fps = float(av.timing.fps)
        if 1 < fps <= 240:
            fps_values.append(fps)
    fps = max(fps_values) if fps_values else 60.0

    step = 1.0 / fps
    return fps, step


def cycle_fade_alpha(elapsed, fade_enabled, fade_duration, cycle_enabled, cycle_seconds):
    fade_alpha = 0

    if fade_enabled and fade_duration > 0:
        if elapsed < fade_duration:
            fade_alpha = max(
                fade_alpha,
                int(round(
                    255.0 * (1.0 - elapsed / fade_duration)
                )),
            )

        if cycle_enabled:
            remaining = cycle_seconds - elapsed
            if remaining < fade_duration:
                fade_alpha = max(
                    fade_alpha,
                    int(round(
                        255.0 * (
                            1.0 - max(0.0, remaining) / fade_duration
                        )
                    )),
                )
    return fade_alpha
