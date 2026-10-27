def format_wait(seconds: int) -> str:
    """Kutish vaqti: «1 daqiqa 20 soniya», «45 soniya»."""
    minutes, secs = divmod(max(1, seconds), 60)
    parts = ([f"{minutes} daqiqa"] if minutes else []) + ([f"{secs} soniya"] if secs else [])
    return " ".join(parts)


def format_deadline(minutes: int) -> str:
    """Muddat «...da» shaklida: «10 daqiqada», «2 soatda», «3 kunda»."""
    if minutes % 1440 == 0:
        return f"{minutes // 1440} kunda"
    if minutes % 60 == 0:
        return f"{minutes // 60} soatda"
    return f"{minutes} daqiqada"
